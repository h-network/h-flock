# Build 37 — a TLS answer that produces a tenant that boots

> One defect, in the installer. `setup.sh` offers TLS and then builds a tenant
> that crash-loops, so the offer is worse than not making it.
>
> **Base on `main`.** Branch `tmux/build-37-tls-install`, push to origin.

⚠ **The door code is correct and is not yours to change.** `flock.api` and
`flock.session` read `API_TLS_CERT` / `API_TLS_KEY` and pass them to uvicorn;
measured serving TLS 1.3 on both doors, `200` with a token, `401` without. This
build is `setup.sh` and the container lifecycle around it.

## 1. What is wrong

`setup.sh:182` asks for a path to a certificate, then:

- **never checks the file exists**
- **writes the host path into `container/.env` as if it were a container path** —
  the door reads it inside the container, where it is not
- runs `docker compose up -d --build`, so the doors start **before** anything
  could copy a certificate in

The result is `FileNotFoundError` in uvicorn and a crash-looping tenant, from an
installer that reported success.

⚠ **Two paths, and conflating them is the whole bug.** Where the certificate is
on the operator's machine, and where the door will look for it inside the
container, are different strings. `.env` must carry the second.

## 2. What it must do

- **Validate.** A path that does not exist on the host stops the installer with
  a message, before anything is built.
- **Offer to generate.** Most people testing this have no certificate. When the
  answer is blank, offer a self-signed one — and say plainly what it costs, that
  anything verifying certificates will reject it.
- **Deliver before boot.** `create` → `docker cp` → `start`, the ordering the
  README already documents. ⚠ Certificates are **never baked into the image and
  never a volume** — same rule as credentials (`LLD-container` §3).
- **Leave plain HTTP exactly as it is.** It works, it is what the browser console
  needs, and it is the answer most people should give.
- **Say what TLS costs at the end.** With TLS chosen, print that the browser
  console cannot reach TLS doors (`clients/web/README.md`), so the operator
  learns it from the installer rather than from a blank terminal.

## 3. Done when

⚠ **Run the installer. Both answers. Paste what happened.** This build exists
because a prompt was written and never answered by the person who wrote it.

- plain HTTP: tenant healthy, console reachable, unchanged from today
- TLS: tenant **healthy** — not "started", healthy — and from the host:
  - `curl -k https://<host>:8080/health` with the token → `200`
  - without the token → `401`
  - plain `http://` at that port → refused
- a bad certificate path stops the installer before it builds anything

## 4. Reporting

`jira done`, then message `architect` with the commit you worked from, what you
changed, and the two installer runs. ⚠ **If you cannot run docker in your lane,
say so and stop at the point you can reach** — an untested installer is what
this build is fixing, and claiming a run you did not do is worse than the bug.
