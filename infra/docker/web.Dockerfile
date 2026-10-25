FROM node:22.14.0-alpine@sha256:9bef0ef1e268f60627da9ba7d7605e8831d5b56ad07487d24d1aa386336d1944 AS tooling

WORKDIR /workspace

COPY package.json package-lock.json ./
COPY .prettierignore ./.prettierignore
COPY apps/web/package.json ./apps/web/package.json
COPY packages/contracts/package.json ./packages/contracts/package.json
RUN npm ci

COPY apps/web ./apps/web
COPY packages/contracts ./packages/contracts

FROM tooling AS build

ARG VITE_TURNSTILE_SITE_KEY=
ENV VITE_TURNSTILE_SITE_KEY=${VITE_TURNSTILE_SITE_KEY}
RUN npm run build

FROM nginx:1.27.4-alpine@sha256:4ff102c5d78d254a6f0da062b3cf39eaf07f01eec0927fd21e219d0af8bc0591 AS runtime

RUN mkdir -p /tmp/nginx/client_body
COPY infra/docker/web.conf /etc/nginx/conf.d/default.conf
COPY --from=build /workspace/apps/web/dist /usr/share/nginx/html

FROM runtime AS production
COPY infra/docker/web.production.conf /etc/nginx/conf.d/default.conf

# Keep local Compose builds on the existing proxy configuration by default.
FROM runtime AS local
