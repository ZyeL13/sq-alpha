# Reaction illustrations

Sketchnote cards on the JIT path carry a mini-polaroid of the avatar
reacting to the post, pasted in the left margin zone. The main
polaroid (top-right) is NOT drawn when a reaction is present.

## Files (32, delivered at deploy time)

8 reactions × 4 rotation variants, 512×512 JPG, white background,
no text:

```
surprise_{a,b,c,d}.jpg   dejavu_{a,b,c,d}.jpg
shrug_{a,b,c,d}.jpg      disbelief_{a,b,c,d}.jpg
question_{a,b,c,d}.jpg   contrast_{a,b,c,d}.jpg
caution_{a,b,c,d}.jpg    smug_{a,b,c,d}.jpg
```

These binaries are NOT committed to git (the snapshot push rejects
binary files). They travel to the VPS as one zip and are extracted
into this directory BEFORE `docker compose up -d --build`, so they
bake into the image (the renderer reads them from
`ILLUSTRATIONS_DIR`, default `assets/illustrations/`).

## Behavior when files are missing

A missing or unreadable illustration degrades gracefully: the card
renders without it (the sparkle stays) and a warning is logged. A
missing file can never fail a render or a post.

## Variant rotation

The renderer peeks the per-reaction round-robin cursor
(`prompts.reactions.current_variant`); the cursor advances only when
a post with that reaction is scheduled (winners only), so the
variant on the card is always the one the post consumes.
