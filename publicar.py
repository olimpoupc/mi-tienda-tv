"""Administra Mi Tienda TV: agrega, actualiza o quita apps del catálogo (tienda.json).

Uso (desde esta carpeta):
  python publicar.py apk RUTA.apk [--desc "texto"]        sube el APK a GitHub (🏠 propia)
  python publicar.py oficial URL [--desc "texto"] [--fijar] enlaza la descarga oficial (🌐)
  python publicar.py editar PAQUETE [--categoria …] [--detalle …] [--novedades …] [--destacada si|no]
  python publicar.py quitar PAQUETE                        quita una app del catálogo
  python publicar.py lista                                 muestra el catálogo

"oficial" descarga el APK una vez solo para leer su nombre, versión e ícono; no lo sube.
Con --fijar guarda también su huella SHA-256: más seguro, pero si el sitio oficial cambia
el archivo, la tienda dirá que no coincide hasta que vuelvas a publicarlo.
"""
import argparse
import datetime
import glob
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile

REPO = "olimpoupc/mi-tienda-tv"
RAW = f"https://raw.githubusercontent.com/{REPO}/main"
HERE = os.path.dirname(os.path.abspath(__file__))
CATALOG = os.path.join(HERE, "tienda.json")
ICONS = os.path.join(HERE, "iconos")


def find_aapt2():
    """Windows PC (LOCALAPPDATA) or GitHub's Ubuntu runners (ANDROID_HOME), newest build-tools first."""
    if os.environ.get("AAPT2"):
        return os.environ["AAPT2"]
    roots = [os.environ.get("ANDROID_HOME"), os.environ.get("ANDROID_SDK_ROOT"),
             os.path.join(os.environ.get("LOCALAPPDATA", ""), "Android", "Sdk")]
    for root in filter(None, roots):
        found = sorted(glob.glob(os.path.join(root, "build-tools", "*", "aapt2*")), reverse=True)
        found = [f for f in found if os.path.basename(f) in ("aapt2", "aapt2.exe")]
        if found:
            return found[0]
    sys.exit("No encontré aapt2 (Android SDK build-tools).")


AAPT2 = find_aapt2()
GH = shutil.which("gh") or r"C:\Program Files\GitHub CLI\gh.exe"


def run(*cmd, check=True):
    r = subprocess.run(cmd, cwd=HERE, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if check and r.returncode != 0:
        sys.exit(f"Falló: {' '.join(cmd)}\n{r.stdout}{r.stderr}")
    return r.stdout


def read_apk(path):
    """Name, version, TV or phone and icon, as aapt2 sees them."""
    out = run(AAPT2, "dump", "badging", path)
    pkg = re.search(r"package: name='([^']+)' versionCode='(\d+)' versionName='([^']*)'", out)
    if not pkg:
        sys.exit("No parece un APK válido.")
    label = re.search(r"application-label(?:-es)?:'([^']*)'", out)
    tv = "leanback-launchable-activity" in out or "android.software.leanback" in out
    icons = re.findall(r"application-icon-(\d+):'([^']+)'", out)
    icon = None
    for _, p in sorted(icons, key=lambda d: -int(d[0])):
        if p.endswith((".png", ".webp", ".jpg")):
            icon = p
            break
    with open(path, "rb") as f:
        sha = hashlib.sha256(f.read()).hexdigest()
    return {
        "id": pkg.group(1),
        "versionCode": int(pkg.group(2)),
        "version": pkg.group(3),
        "nombre": label.group(1) if label and label.group(1) else pkg.group(1),
        "tv": tv,
        "tamano": os.path.getsize(path),
        "sha256": sha,
        "_icon": icon,
    }


def save_icon(apk_path, info):
    """Copies the app's icon into iconos/ so the store can show it."""
    info.pop("icono", None)
    entry = info.pop("_icon")
    if not entry:
        return
    os.makedirs(ICONS, exist_ok=True)
    ext = os.path.splitext(entry)[1]
    name = info["id"] + ext
    with zipfile.ZipFile(apk_path) as z, open(os.path.join(ICONS, name), "wb") as f:
        f.write(z.read(entry))
    info["icono"] = f"{RAW}/iconos/{name}"


def load():
    if subprocess.run(["git", "rev-parse", "--abbrev-ref", "@{u}"], cwd=HERE, capture_output=True).returncode == 0:
        run("git", "pull", "--rebase", "--autostash", check=False)
    with open(CATALOG, encoding="utf-8") as f:
        return json.load(f)


def save(cat, message):
    cat["apps"].sort(key=lambda a: a["nombre"].lower())
    with open(CATALOG, "w", encoding="utf-8", newline="\n") as f:
        json.dump(cat, f, ensure_ascii=False, indent=2)
        f.write("\n")
    run("git", "add", "-A", "tienda.json", *(["iconos"] if os.path.isdir(ICONS) else []))
    if subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=HERE).returncode == 0:
        print("El catálogo ya estaba así; no hay cambios que guardar.")
        return
    run("git", "commit", "-m", message + "\n\nCo-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>")
    # The phone panel and this PC may both publish: take the other's changes first.
    run("git", "pull", "--rebase", "--autostash")
    run("git", "push")


# What a person writes about an app (not read from the APK). A new version keeps them unless new ones
# are given, except "novedades", which belongs to one version.
EDITABLE = ("descripcion", "categoria", "detalle", "novedades", "destacada")


def written(args):
    """The editable fields given on the command line; None means "not given, keep what's there"."""
    vals = {
        "descripcion": args.desc,
        "categoria": args.categoria,
        "detalle": args.detalle,
        "novedades": args.novedades,
        "destacada": None if args.destacada is None else args.destacada == "si",
    }
    return {k: v for k, v in vals.items() if v is not None}


def upsert(cat, info, given):
    old = next((a for a in cat["apps"] if a["id"] == info["id"]), {})
    for k in EDITABLE:
        if k in given:
            info[k] = given[k]
        elif k == "novedades" and old.get("versionCode") != info.get("versionCode"):
            info[k] = ""
        else:
            info[k] = old.get(k, False if k == "destacada" else "")
    info["fecha"] = datetime.date.today().isoformat()
    cat["apps"] = [a for a in cat["apps"] if a["id"] != info["id"]] + [info]


def cmd_apk(args):
    info = read_apk(args.ruta)
    save_icon(args.ruta, info)
    tag = f"{info['id']}-{info['versionCode']}"
    asset = f"{tag}.apk"
    tmp = os.path.join(tempfile.mkdtemp(), asset)
    with open(args.ruta, "rb") as src, open(tmp, "wb") as dst:
        dst.write(src.read())
    exists = subprocess.run([GH, "release", "view", tag, "-R", REPO], capture_output=True).returncode == 0
    if exists:
        run(GH, "release", "upload", tag, tmp, "--clobber", "-R", REPO)
    else:
        run(GH, "release", "create", tag, tmp, "-R", REPO, "--title", f"{info['nombre']} {info['version']}",
            "--notes", f"{info['nombre']} {info['version']} ({info['id']})")
    info.update(fuente="propia", apk=f"https://github.com/{REPO}/releases/download/{tag}/{asset}")
    cat = load()
    upsert(cat, info, written(args))
    save(cat, f"Publicar {info['nombre']} {info['version']}")
    print(f"✅ {info['nombre']} {info['version']} publicada (🏠 propia, {'📺 TV' if info['tv'] else '📱 celular'}).")


def cmd_oficial(args):
    tmpdir = tempfile.mkdtemp()
    path = os.path.join(tmpdir, "oficial.apk")
    print("Descargando una vez para leer la información…")
    req = urllib.request.Request(args.url, headers={"User-Agent": "MiTiendaTV"})
    with urllib.request.urlopen(req) as r, open(path, "wb") as f:
        f.write(r.read())
    with open(path, "rb") as f:
        if f.read(2) != b"PK":
            sys.exit("❌ Ese enlace no descarga un .apk: lleva a una página web. "
                     "Usa el enlace directo al archivo (el que se obtiene al tocar Descargar).")
    info = read_apk(path)
    save_icon(path, info)
    if not args.fijar:
        info["sha256"] = ""
    info.update(fuente="oficial", apk=args.url)
    cat = load()
    upsert(cat, info, written(args))
    save(cat, f"Enlazar {info['nombre']} {info['version']} (oficial)")
    print(f"✅ {info['nombre']} {info['version']} enlazada (🌐 oficial{', huella fijada' if args.fijar else ''}).")


def cmd_quitar(args):
    cat = load()
    before = len(cat["apps"])
    cat["apps"] = [a for a in cat["apps"] if a["id"] != args.paquete]
    if len(cat["apps"]) == before:
        sys.exit(f"{args.paquete} no está en el catálogo.")
    for ext in (".png", ".webp", ".jpg"):
        p = os.path.join(ICONS, args.paquete + ext)
        if os.path.exists(p):
            os.remove(p)
    save(cat, f"Quitar {args.paquete}")
    print(f"✅ {args.paquete} quitada del catálogo. Sus archivos en Releases siguen allí; bórralos en GitHub si quieres.")


def cmd_editar(args):
    """Changes what's written about an app, without uploading it again."""
    cat = load()
    app = next((a for a in cat["apps"] if a["id"] == args.paquete), None)
    if not app:
        sys.exit(f"{args.paquete} no está en el catálogo.")
    given = written(args)
    if not given:
        sys.exit("No indicaste nada que cambiar.")
    app.update(given)
    save(cat, f"Editar {app['nombre']}")
    print(f"✅ {app['nombre']}: datos actualizados ({', '.join(given)}).")


def cmd_lista(_):
    for a in load()["apps"]:
        print(f"{'⭐' if a.get('destacada') else '  '}{'📺' if a['tv'] else '📱'} {'🏠' if a['fuente'] == 'propia' else '🌐'}"
              f"  {a['nombre']} {a['version']}  [{a.get('categoria') or 'sin categoría'}]"
              f"  ({a['id']}, {a['tamano'] / 1048576:.1f} MB)")


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(description="Administra Mi Tienda TV")
    sub = p.add_subparsers(dest="cmd", required=True)

    def texts(sp):
        sp.add_argument("--desc", help="texto corto bajo el nombre")
        sp.add_argument("--categoria", help="por ejemplo: Películas, Música, Juegos, Utilidades")
        sp.add_argument("--detalle", help="descripción larga para la ficha")
        sp.add_argument("--novedades", help="qué trae esta versión")
        sp.add_argument("--destacada", choices=["si", "no"], help="mostrarla primero en la tienda")

    a = sub.add_parser("apk"); a.add_argument("ruta"); texts(a)
    o = sub.add_parser("oficial"); o.add_argument("url"); o.add_argument("--fijar", action="store_true"); texts(o)
    e = sub.add_parser("editar"); e.add_argument("paquete"); texts(e)
    q = sub.add_parser("quitar"); q.add_argument("paquete")
    sub.add_parser("lista")
    args = p.parse_args()
    {"apk": cmd_apk, "oficial": cmd_oficial, "editar": cmd_editar, "quitar": cmd_quitar, "lista": cmd_lista}[args.cmd](args)


if __name__ == "__main__":
    main()
