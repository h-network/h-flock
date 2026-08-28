# container/home

Dotfiles, ssh keys and CLI credentials copied **into** a running tenant, and
copied back **out** after an interactive login.

Everything here except this file is gitignored and never enters the image —
`docker cp` after start, not a `COPY` at build and not a volume.

    container/home/
      .ssh/                    keys for cloning private repos
      .gitconfig               name and email for commits
      .claude/.credentials.json        the default account's login
      .claude-<profile>/.credentials.json   an extra account's
      .codex/auth.json
      .gemini/antigravity-cli/antigravity-oauth-token

Nothing needs to be present. `seed-home.sh --tenant NAME` copies whatever is here and skips
what is not, so an office with no accounts still comes up — its agents just
reach a login prompt.

## Why not a volume

A volume would work and is more to operate: a named thing to create, back up and
remember. This is a directory you can read, edit and copy, and it is the pattern
h-office arrived at after running offices for real.

## Why not baked into the image

Secrets in an image are secrets in every copy of that image, in the layer cache,
and in anywhere it is pushed. The image is rebuilt constantly here; these are
not.
