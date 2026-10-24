# Kling 4 retail tariff

Kling 4 uses the existing Telegram administration price section and remains
compatible with the versioned internal-admin tariff publisher. No retail
default is embedded in source code or in `data/price.json`.

Telegram navigation:

```text
Admin → Prices → Video → Kling → Kling 4
```

The Kling 4 screen always shows six buttons, including before any rate exists.
Selecting a button asks for one positive rate; sending the number saves and
reloads that cell immediately through the ordinary price manager. Reopening the
same cell reads the saved value. Until all six cells exist, generation remains
blocked as not configured.

The block must contain all six positive finite per-billed-second rates:

```text
billing_rates:
  reference: {720p: <positive number>, 1080p: <positive number>}
  keyframe:  {720p: <positive number>, 1080p: <positive number>}
  video:     {720p: <positive number>, 1080p: <positive number>}
```

These dimensions mirror the existing Kling 4 provider quote:

- `reference`: Reference mode without an ordinary video reference;
- `keyframe`: Keyframe mode;
- `video`: Reference mode with one or more ordinary video references;
- quality: `720p` or `1080p`;
- billed seconds: output duration for `reference`/`keyframe`; for `video`, the
  already measured provider rule `output + max(output, ceil(total input video
  seconds))`.

Aspect ratio, Elements, Voice assets and original-sound selection do not have
independent retail multipliers because the current measured provider contract
does not price them independently.

The versioned tariff publishing endpoint validates every supplied Kling 4 cell
and rejects unknown categories/qualities or invalid numbers. It may preserve a
safe partial draft while the admin fills the six cells; quote/launch requires
the complete block. A missing or partial block is shown as
`Цена Kling 4 не настроена` and prevents submission.
The frozen launch quote stores the nominal `cost`, its tariff revision and the
provider credits separately. Kling 4 remains admin-only: `charge_cost` is zero,
and the administrator sees the nominal price plus the explicit notice that no
balance is deducted.

The generic `generation_tasks.cost` remains the amount actually charged and is
therefore zero for Kling 4 administrators. The nominal cost lives in the frozen
quote as `quote.cost`; `quote.charge_cost` remains zero. Kling 4 tasks are owned
by their lifecycle and excluded from the generic watchdog refund path, so a
nominal display price cannot create an administrator refund.

Both Telegram and the Mini App render the frozen nominal `quote.cost`. They show
the administrator exemption separately instead of replacing the configured
price with zero. Integer rates remain editable as decimal rates in the existing
admin price screen.

### Telegram duration controls

Кнопки длительности «−1с», «+1с» и текущего значения обновляют существующую карточку и стоимость через editMessageText. Новое сообщение не отправляется, в том числе при достижении границ длительности или неизменном значении.

### Пользовательские сообщения

Telegram и форма генерации Mini App показывают пользовательскую цену и понятные статусы. Закупочные расходы, credits, внутренние ID задач, сырые статусы, формы ручной привязки провайдера и JSON-настройки скрыты из генерационного интерфейса. Технические данные остаются в backend и логах; API диагностики и конфигурации сохраняются.
