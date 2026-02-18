FROM node:22-alpine AS builder

WORKDIR /app

COPY package.json package-lock.json ./

RUN npm ci

COPY . .

RUN npm run build

FROM nginx:1.26.0-alpine

COPY --from=builder /app/dist /usr/share/nginx/html/ui

COPY nginx.conf /etc/nginx/conf.d/default.conf