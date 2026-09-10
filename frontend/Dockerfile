# Build stage: produces the static bundle.
FROM node:22-alpine AS build

WORKDIR /app

COPY package*.json ./
RUN npm ci

COPY . .
# No API address is baked in: the client resolves it from the host the panel
# was served from, so one image works on localhost and on any LAN address.
RUN npm run build

# Serve stage: nginx with the bundle only — no Node, no source.
FROM nginx:alpine

COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80
