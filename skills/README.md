# Habilidades para la futura fase de frontend

Solicitadas por el usuario el 2026-10-04. El frontend permanece en pausa hasta
que el usuario autorice expresamente iniciarlo. Guardar estas instrucciones
no autoriza modificar la interfaz ni añadir dependencias de frontend.

Fuente: https://github.com/leonxlnx/taste-skill

- [gpt-taste](gpt-taste/SKILL.md)
- [minimalist-ui](minimalist-ui/SKILL.md)

Se ejecutaron los dos comandos exactos `npx skills use ... --skill ...`.
Fallaron con Node 20.14.0: `node:zlib` no exportaba `crc32`.
Ambos se ejecutaron correctamente con un Node 22.22.0 temporal:

```powershell
npx --yes --package=node@22.22.0 --package=skills skills use "https://github.com/leonxlnx/taste-skill" --skill "gpt-taste"
npx --yes --package=node@22.22.0 --package=skills skills use "https://github.com/leonxlnx/taste-skill" --skill "minimalist-ui"
```

Se leyó toda la salida. Cada carpeta contiene su `SKILL.md` íntegro y
`salida-completa.txt`, incluidos los mensajes del ejecutor. No se proporcionó
un directorio de archivos de apoyo ni rutas relativas que resolver. No se
actualizó Node global, package.json ni el lockfile del proyecto.

Son instrucciones locales del proyecto, disponibles para la siguiente fase;
no se afirma una instalación global en el catálogo de Codex. Las instrucciones
del usuario prevalecen sobre estas habilidades. Las directrices que se
contradicen entre ellas deberán conciliarse al iniciar el frontend, manteniendo
la función académica de los cuatro paneles y el mapa. La habilidad más reciente
(`minimalist-ui`) orienta la paleta y el movimiento discreto; no se introduce
una landing promocional ni dependencias de animación por anticipado.
