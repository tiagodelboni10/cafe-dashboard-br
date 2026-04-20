"""
Endpoint para receber pedidos gerados pelo dashboard de estoque.
Commita o pedido como JSON no repositorio em pedidos_pendentes/.
Um worker no PC que roda o VR Master vai puxar os pedidos periodicamente
e criar no banco.
"""
import base64
import hashlib
import json
import os
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler

GITHUB_REPO = "tiagodelboni10/cafe-dashboard-br"
GITHUB_BRANCH = "master"
PASTA_PENDENTES = "pedidos_pendentes"


class handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_POST(self):
        try:
            content_length = int(self.headers.get("Content-Length", 0))
            if content_length <= 0 or content_length > 5 * 1024 * 1024:
                return self._error(400, "Payload vazio ou muito grande")
            raw = self.rfile.read(content_length)
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                return self._error(400, "JSON invalido")

            erro = _validar_payload(payload)
            if erro:
                return self._error(400, erro)

            token = os.environ.get("GITHUB_TOKEN")
            if not token:
                return self._error(500, "GITHUB_TOKEN nao configurado no Vercel")

            tz_br = timezone(timedelta(hours=-3))
            now = datetime.now(tz_br)

            # Anexar metadata de recebimento
            payload.setdefault("_meta", {})
            payload["_meta"].update({
                "recebido_em": now.isoformat(),
                "origem": payload.get("origem", "dashboard"),
            })

            ts = now.strftime("%Y%m%d_%H%M%S")
            digest = hashlib.sha256(raw).hexdigest()[:6]
            filename = f"pedido_{ts}_{digest}.json"
            path = f"{PASTA_PENDENTES}/{filename}"

            conteudo = json.dumps(payload, indent=2, ensure_ascii=False)
            b64 = base64.b64encode(conteudo.encode("utf-8")).decode("ascii")

            total_itens = sum(len(p.get("itens", [])) for p in payload["pedidos"])
            num_forns = len(payload["pedidos"])
            msg_commit = f"Pedido: {num_forns} fornecedor(es), {total_itens} item(ns)"

            url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{path}"
            req = urllib.request.Request(
                url,
                data=json.dumps({
                    "message": msg_commit,
                    "content": b64,
                    "branch": GITHUB_BRANCH,
                }).encode("utf-8"),
                method="PUT",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/vnd.github+json",
                    "Content-Type": "application/json",
                    "User-Agent": "vrmaster-pedido",
                },
            )
            try:
                with urllib.request.urlopen(req, timeout=20) as r:
                    resp = json.loads(r.read())
                commit_sha = resp.get("commit", {}).get("sha")
                return self._ok({
                    "ok": True,
                    "arquivo": path,
                    "commit": commit_sha,
                    "pedidos": num_forns,
                    "itens": total_itens,
                })
            except urllib.error.HTTPError as e:
                detalhe = e.read().decode("utf-8", "replace")[:300]
                return self._error(502, f"GitHub API {e.code}: {detalhe}")

        except Exception as e:
            return self._error(500, str(e))

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _ok(self, body):
        self.send_response(200)
        self._cors()
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(body).encode("utf-8"))

    def _error(self, code, msg):
        self.send_response(code)
        self._cors()
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"error": msg}).encode("utf-8"))


def _validar_payload(p):
    if not isinstance(p, dict):
        return "Payload deve ser objeto"
    for f in ("data_compra", "id_loja", "id_comprador", "pedidos"):
        if f not in p:
            return f"Campo '{f}' obrigatorio"
    if not isinstance(p["pedidos"], list) or not p["pedidos"]:
        return "Campo 'pedidos' deve ser lista nao vazia"
    for idx, pedido in enumerate(p["pedidos"]):
        if not isinstance(pedido, dict):
            return f"pedido {idx} invalido"
        if "id_fornecedor" not in pedido or "itens" not in pedido:
            return f"pedido {idx}: campos obrigatorios ausentes"
        if not isinstance(pedido["itens"], list) or not pedido["itens"]:
            return f"pedido {idx}: itens deve ser lista nao vazia"
        for it in pedido["itens"]:
            if not isinstance(it, dict):
                return f"pedido {idx}: item invalido"
            if "id_produto" not in it or "quantidade" not in it:
                return f"pedido {idx}: item sem id_produto ou quantidade"
            try:
                q = float(it["quantidade"])
                if q <= 0:
                    return f"pedido {idx}: quantidade deve ser positiva"
            except (TypeError, ValueError):
                return f"pedido {idx}: quantidade invalida"
    return None
