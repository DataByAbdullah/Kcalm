# Recipe images

Images belong to Recipe and are display metadata. Planning, reading plans and
swapping meals never call OpenAI or object storage. Existing and archived daily
plans resolve the current Recipe URL, so generating an image later also updates
their presentation without changing nutrition, servings, times or snapshots.

## Deployment and generation

Install `requirements.txt` and apply `alembic upgrade head`. Configure the separate
image settings from `.env.example`, including `OPENAI_API_KEY`, the storage bucket,
region, access key, secret key and public base URL. For Cloudflare R2, set the S3
endpoint and use region `auto`. For AWS S3, the endpoint can remain empty.

The bucket/CDN must provide public delivery through `IMAGE_STORAGE_PUBLIC_BASE_URL`.
The application sets no object ACLs. WebP objects use versioned keys and immutable
one-year cache headers. The default image model is `gpt-image-2.6-flare`, with one
1024x1024 image, medium quality, low complexity and compression 85. The image
timeout defaults to 180 seconds; text-model settings remain independent.

Run explicitly in Railway or the backend environment:

```sh
python -m app.scripts.generate_recipe_images
python -m app.scripts.generate_recipe_images --limit 5
python -m app.scripts.generate_recipe_images --recipe-id <recipe-uuid>
python -m app.scripts.generate_recipe_images --recipe-id <recipe-uuid> --force
```

The command skips ready images, continues after failures, prints a final
ready/skipped/generated/failed/total summary, and exits with status 1 if any recipe
failed. Nothing generates automatically at startup, deployment or recipe reseeding.

Admins can also call `POST /api/v1/recipes/{recipe_id}/image/generate` with
`{"force": false}` (the body is optional). The response contains `recipe_id`,
`image_url`, `image_status`, `image_model` and `image_generated_at`. Normal users
cannot trigger generation. Recipe, candidate and meal response items expose only
the additional `image_url` field.

## Failure and concurrency behavior

A ready image is reused without contacting either provider. Forced regeneration
uses a new object key. If it fails, the previous successful URL and metadata stay
ready; a sanitized diagnostic is saved in `image_error`. A failed first generation
has status `failed` and no image URL. Missing configuration produces the controlled
`RECIPE_IMAGE_CONFIGURATION_MISSING` error. No provider exception text or storage
credentials are returned or logged.

Generation claims are committed before external requests. A second concurrent
request receives `RECIPE_IMAGE_GENERATION_IN_PROGRESS`. The internal claim token
and start timestamp let a later request recover an interrupted job after the image
timeout plus 180 seconds. A superseded worker cannot overwrite a newer result.
OpenAI automatic retries are disabled to avoid duplicate paid generation after a
timeout. Storage requests have bounded retries. Deleting a superseded old object is
best effort and cannot fail a successful regeneration.
If a database commit loses its acknowledgment, cleanup checks the saved metadata
before deleting an uploaded object, preserving an image that was already committed.

Recipe seed updates own recipe content, not image metadata. Reseeding preserves
the Recipe ID, image URL, object key, status, prompt, model and generated timestamp.
