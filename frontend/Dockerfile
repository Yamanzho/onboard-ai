FROM node:22-alpine AS build

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY . .

# Empty base URL → browser calls same origin; nginx proxies /api → api:8000
ENV VITE_API_BASE_URL=
RUN npm run build

# Non-root nginx (F-05/gate): listen on 8080 (no privileged bind).
# Production compose maps 127.0.0.1:3000→8080 (F-07 edge contract unchanged).
FROM nginx:1.27-alpine

ARG NGINX_CONF=nginx.conf
COPY ${NGINX_CONF} /etc/nginx/conf.d/default.conf
COPY --from=build --chown=nginx:nginx /app/dist /usr/share/nginx/html

RUN chown -R nginx:nginx /var/cache/nginx /var/log/nginx /etc/nginx/conf.d \
    && touch /var/run/nginx.pid \
    && chown nginx:nginx /var/run/nginx.pid

USER nginx

EXPOSE 8080

CMD ["nginx", "-g", "daemon off;"]
