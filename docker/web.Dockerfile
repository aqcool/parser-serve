ARG NODE_BASE_IMAGE=node:22-bookworm-slim
ARG NGINX_BASE_IMAGE=nginx:1.27-alpine

FROM ${NODE_BASE_IMAGE} AS build
WORKDIR /web
COPY web/package.json ./
# Replace this with `npm ci` after package-lock.json is committed.
RUN npm install --no-audit --no-fund
COPY web ./
RUN npm run build

FROM ${NGINX_BASE_IMAGE}
COPY docker/web-nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /web/dist /usr/share/nginx/html
EXPOSE 8080
