# Mi Tienda TV

Catálogo privado de apps para **Mi Instalador** (Android TV / cajas Claro).

- `tienda.json` — la lista de apps que muestra la pestaña **Tienda**.
- **Releases** — los APK alojados aquí. Cada app tiene su enlace directo y su huella SHA-256.
- Algunas apps apuntan a su **página oficial** en vez de estar alojadas aquí.

Las apps se agregan con el script `publicar` desde el computador del administrador.
Úsalas bajo tu propia responsabilidad.

## Para el administrador (desde el computador)

```
python publicar.py apk RUTA.apk --desc "texto corto"     # sube tu APK (🏠)
python publicar.py oficial URL --desc "texto corto"      # enlaza la descarga oficial (🌐)
python publicar.py oficial URL --fijar                   # igual, pero verificando la huella
python publicar.py lista                                 # ver el catálogo
python publicar.py quitar com.paquete.app                # quitar una app
```

Para publicar una versión nueva de una app, vuelve a correr el mismo comando con el APK nuevo:
la tienda mostrará **Actualizar** en las cajas que tengan la versión anterior.
