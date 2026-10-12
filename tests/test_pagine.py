import re
from dataclasses import replace
from pathlib import Path

from rbvecchi.web import create_app, impronta_static
from test_monitor import settings


def client(tmp_path: Path):
    app = create_app(replace(settings(tmp_path), raccolta_dir=tmp_path), start_monitor=False)
    c = app.test_client()
    c.post("/login", data={"username": "admin", "password": "password"})
    return c


def test_navigazione_comune(tmp_path: Path) -> None:
    c = client(tmp_path)
    for url, attiva in (("/", "/"), ("/ricarica", "/ricarica"), ("/dettagli", "/dettagli")):
        html = c.get(url).get_data(as_text=True)
        assert 'class="nav"' in html
        for voce in ("/", "/ricarica", "/dettagli"):
            assert f'<a href="{voce}"' in html
        assert re.findall(r'<a href="([^"]+)" aria-current="page"', html) == [attiva]
        assert 'action="/logout"' in html
        assert 'name="csrf-token"' in html
        assert 'id="i-garage"' in html                       # sprite delle icone


def test_login_senza_navigazione(tmp_path: Path) -> None:
    app = create_app(replace(settings(tmp_path), raccolta_dir=tmp_path), start_monitor=False)
    html = app.test_client().get("/login").get_data(as_text=True)
    assert 'name="username"' in html and 'name="password"' in html
    assert 'class="nav"' not in html and "csrf-token" not in html and "common.js" not in html


def test_css_e_js_con_versione(tmp_path: Path) -> None:
    html = client(tmp_path).get("/ricarica").get_data(as_text=True)
    v = impronta_static(Path(__file__).resolve().parent.parent / "rbvecchi" / "static")
    for nome in ("app.css", "common.js", "ricarica.js"):
        assert f"/static/{nome}?v={v}" in html
    assert re.search(r"<style|style=", html) is None              # CSP: niente stili in linea
    assert re.search(r"<script>|<script [^>]*>[^<]", html) is None  # né script in linea


def test_impronta_cambia_con_i_file(tmp_path: Path) -> None:
    (tmp_path / "a.css").write_text("x")
    prima = impronta_static(tmp_path)
    (tmp_path / "a.css").write_text("y")
    assert impronta_static(tmp_path) != prima
