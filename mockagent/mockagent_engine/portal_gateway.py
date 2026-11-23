# -*- coding: utf-8 -*-
"""场景 Portal 网关：静态托管 openan-portal 构建产物 + API 反代（nginx 的轻量等价物）。

每场景一个实例：
- GET /                → portal/dist 静态文件（SPA fallback 到 index.html）
- /api/orchestrate/、/rest/v1/orchestrate/ → 编排中心后台（场景独立端口）
- /api/registry-center/、/api/registry/   → 注册中心（场景独立端口）

路由由环境变量注入（deploy_scenario_portal.py 拉起时写入）：
    PORTAL_DIST_DIR=<portal/dist 绝对路径>
    PORTAL_ROUTES_JSON=[{"prefix":"/api/orchestrate/","upstream":"http://127.0.0.1:9101"}, ...]

直接运行：python -m mockagent_engine.portal_gateway（配合上述环境变量与 PORTAL_PORT）。
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import httpx
from fastapi import FastAPI, Request, Response
from fastapi.staticfiles import StaticFiles

HOP_BY_HOP = {"connection", "keep-alive", "transfer-encoding", "te", "trailer", "proxy-authenticate", "proxy-authorization", "upgrade"}


def create_app(dist_dir: str | Path | None = None, routes: list[dict] | None = None) -> FastAPI:
    dist = Path(dist_dir or os.environ.get("PORTAL_DIST_DIR", "")).resolve()
    if not (dist / "index.html").is_file():
        raise RuntimeError(f"portal dist 无效（缺少 index.html）：{dist}")
    route_defs = routes if routes is not None else json.loads(os.environ.get("PORTAL_ROUTES_JSON", "[]"))
    for r in route_defs:
        if not r.get("prefix") or not r.get("upstream"):
            raise RuntimeError(f"网关路由缺少 prefix/upstream：{r}")
    display_routes = list(route_defs)
    route_defs.sort(key=lambda r: len(r["prefix"]), reverse=True)  # 长前缀优先

    app = FastAPI(title="OpenAN Portal Gateway (scenario)", docs_url=None, redoc_url=None, openapi_url=None)

    @app.get("/healthz")
    async def healthz():
        return {"status": "ok", "dist": str(dist), "routes": [r["prefix"] for r in display_routes]}

    async def _proxy(request: Request, upstream: str, strip_prefix: str = "") -> Response:
        path = request.scope["path"]
        if strip_prefix:
            path = path[len(strip_prefix):] or "/"
        target = upstream.rstrip("/") + path
        if request.scope.get("query_string"):
            target += "?" + request.scope["query_string"].decode("latin-1")
        headers = {k: v for k, v in request.headers.items() if k.lower() not in HOP_BY_HOP and k.lower() != "host"}
        body = await request.body()
        # 每请求独立 client：避免跨事件循环复用连接池（TestClient/多 worker 场景）
        try:
            async with httpx.AsyncClient(timeout=60.0, trust_env=False) as client:
                resp = await client.request(request.method, target, headers=headers, content=body, follow_redirects=False)
        except httpx.HTTPError as exc:
            return Response(
                json.dumps({"detail": f"upstream {upstream} unreachable: {exc}"}),
                status_code=502, media_type="application/json",
            )
        out_headers = {k: v for k, v in resp.headers.items() if k.lower() not in HOP_BY_HOP}
        return Response(content=resp.content, status_code=resp.status_code, headers=out_headers)

    @app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"])
    async def catch_all(request: Request) -> Response:
        path = request.scope["path"]
        for route in route_defs:
            if path.startswith(route["prefix"]):
                return await _proxy(request, route["upstream"], route.get("stripPrefix", ""))
        # SPA：静态文件存在则回文件，否则回 index.html（前端路由）
        candidate = (dist / path.lstrip("/")).resolve()
        if candidate.is_file() and str(candidate).startswith(str(dist)):
            return Response(content=candidate.read_bytes(), media_type=_media_type(candidate))
        index = dist / "index.html"
        return Response(content=index.read_bytes(), media_type="text/html")

    def _media_type(path: Path) -> str:
        import mimetypes

        return mimetypes.guess_type(str(path))[0] or "application/octet-stream"

    app.state.portal_dist = dist
    app.state.routes = route_defs
    return app


def main() -> None:  # pragma: no cover - 由部署脚本拉起
    import uvicorn

    port = int(os.environ.get("PORTAL_PORT", "9103"))
    host = os.environ.get("PORTAL_HOST", "127.0.0.1")
    uvicorn.run(create_app(), host=host, port=port, log_level="warning")


if __name__ == "__main__":
    main()
