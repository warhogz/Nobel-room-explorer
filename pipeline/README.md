# Конвейер NOBEL ISLAND KITCHEN

Все команды из корня проекта (`NOBEL ISLAND KITCHEN/`). Пути к программам:

```
MAXB="C:\Program Files\Autodesk\3ds Max 2026\3dsmaxbatch.exe"
BLENDER="C:\Program Files (x86)\Steam\steamapps\common\Blender\blender.exe"
PY="%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
```

## 1. 3ds Max (batch, без GUI)

```powershell
$env:NIK_OUT = "$PWD\build\dump"
& $MAXB pipeline\max\dump_scene.py -sceneFile 3DMAX\SCENE\Island_Israel.max      # дамп сцены -> build/dump/*.json
& $PY pipeline\max\summarize_dump.py build\dump                                   # -> build/dump/SUMMARY.md

$env:NIK_MAX = "$PWD\3DMAX\SCENE\Island_Israel.max"; $env:NIK_EXPORT = "$PWD\build\export"
& $MAXB pipeline\max\export_fbx.py                                                # -> build/export/scene.fbx
```

`3dsmaxbatch` всегда завершается кодом 126 / -130 — это норма; смотреть `export.log` / `progress.log`.
`pipeline/max/scene_census.py <file.max>` считает реальные записи в потоке Scene (без загрузки Max).

## 2. Материалы Corona → PBR

```powershell
$env:NIK_HERO_MTLS = '["Material #-2147483589", "Material #76111117"]'   # оникс и орех в 4K
& $PY pipeline\materials\compile_materials.py build\dump build\tex_src build\materials
```

`build/tex_src` — распакованный `3DMAX/TEXTURE/Island_Israel_tex.zip`.

## 3. Blender (headless)

```powershell
& $BLENDER -b --factory-startup -P pipeline\blender\build_scene.py -- "$PWD"                     # -> build/blender/scene.blend
& $BLENDER -b build\blender\scene.blend -P pipeline\blender\bake_lightmaps.py -- "$PWD\build\bake" 1024
& $BLENDER -b build\blender\scene.blend -P pipeline\blender\export_glb.py -- "$PWD\build\web\scene.glb"
& $BLENDER -b build\blender\scene.blend -P pipeline\blender\cameras.py -- <outdir> 96             # проверочные рендеры камер
```

Запекание: 4 объекта × 3 группы (`kitchen`, `ostrov`, `pol`), RTX 5070 ≈ 4 мин при 1024 сэмплах.
Параметры: `bake_lightmaps.py <out> <samples> [Obj1,Obj2|*] [LM_kitchen,...|*]`.

## 4. Веб-ассеты и приложение

```powershell
& $PY pipeline\web\build_assets.py "$PWD"     # -> web/public/assets
cd web; npm run dev                            # http://127.0.0.1:5180 ;  ?dev — панель калибровки и решатель камер
npm run build                                  # статическая сборка в web/dist (относительные пути)
```

В режиме `?dev` в консоли браузера доступны `__nik` (сцена, LightMix, стор), `__cam` (пресеты, контроллер),
`__solveCamera(spec)` и `__cameraSpecs(pedestal, faucetTop)` — подбор камер под рендеры заказчика.
