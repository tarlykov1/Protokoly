# Nginx demo configuration

Default config is HTTP-only for reproducible smoke tests. For a public server `demo.example.ru`, add a TLS `server` block with certificates mounted from `certs/` and redirect port 80 to 443.

Generate Basic Auth file (not committed):

```bash
mkdir -p deploy/nginx/auth
htpasswd -Bc deploy/nginx/auth/.htpasswd demo-admin
```

If `htpasswd` is unavailable: `openssl passwd -apr1` can generate password hashes for the file.
