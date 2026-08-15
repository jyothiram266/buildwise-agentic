FROM docker.io/library/nginx:alpine

RUN apk add --no-cache apache2-utils

COPY deploy/nginx/nginx.conf /etc/nginx/conf.d/default.conf
COPY deploy/nginx/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 80

ENTRYPOINT ["/entrypoint.sh"]
