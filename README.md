# Nobel Island Kitchen

Интерактивная 3D-сцена кухни Nobel Island Kitchen на React, Three.js и Vite.

## Запуск

Требуется Node.js 24 или новее.

```powershell
cd web
npm ci
npm run dev
```

Для production-сборки выполните `npm run build` в папке `web`. Результат появится в `web/dist`.

## Структура

- `web/` — приложение, статические ресурсы и готовые для браузера 3D-ассеты.
- `pipeline/` — скрипты подготовки сцены, материалов, lightmap и веб-ассетов.
- `3DMAX/` — исходная сцена 3ds Max, текстуры и референсные рендеры.

Скрипты конвейера рассчитаны на 3ds Max, Blender и Python; их команды и параметры описаны в `pipeline/README.md`.

Большие исходные файлы 3ds Max и архив текстур хранятся через Git LFS; готовые веб-ассеты (`*.glb`, `*.ktx2`) тоже.

## Сцена: кухня и двусветный зал

Веб-сцена собрана из полного файла виллы (Option 9; сам файл 3,2 ГБ в репозиторий не входит):

- запечённый в Cycles свет 235 светильников Corona (IES, LightMix), солнце и небо; карты света очищены
  денойзером OIDN и хранятся в HDR (KTX2 E5B9G9R9), плотная мебель освещена по вершинам;
- отражения от зондов, снятых с самой комнаты; переключатель Day / Evening;
- виды — настоящие камеры рендеров Corona; «Compare with render» накладывает рендер на кадр;
- камера-«пружина» не проходит сквозь стены; режим Walk — ходьба от первого лица (WASD / стрелки, мышь,
  клик по полу, джойстик на телефоне) с коллизиями;
- прелоадер показывает реальный прогресс (байты всех файлов, распаковка, компиляция шейдеров) и открывает сцену,
  только когда она готова.

Конвейер комнаты: `pipeline/max/export_room.py` → `pipeline/materials/compile_materials.py --room` →
`pipeline/blender/build_room.py` → `bake_room.py` → `denoise_lightmaps.py` → `export_room_glb.py` →
`pipeline/web/build_room_assets.py`; люстра — `pipeline/max/export_chandelier.py` + `pipeline/blender/build_chandelier.py`.
