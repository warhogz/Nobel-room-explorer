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

Большие исходные файлы 3ds Max и архив текстур хранятся через Git LFS.
