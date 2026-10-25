# Kling 4 retail tariff

Kling 4 uses the existing Telegram administration price section and the
versioned tariff publisher. No retail default is embedded in source code. The
mutable `data/price.json` block is the source of truth for both the six rates
and the public rollout switch.

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
public_enabled: <boolean>
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
`Цена Kling 4 не настроена` and prevents submission. `public_enabled: true` is
accepted only with a complete valid tariff. Removing the flag or setting it to
`false` immediately restores administrator-only launch access.

The frozen launch quote stores the nominal `cost`, payable `charge_cost`, its
tariff revision and provider credits separately. For ordinary users,
`charge_cost == cost`; administrators keep `charge_cost == 0` and see the
nominal price with an explicit exemption.

The generic `generation_tasks.cost` remains the amount actually charged. The
Kling lifecycle atomically creates the intent and task and debits an ordinary
user before the provider request. A proven provider rejection or asynchronous
failure refunds the frozen charge exactly once. An ambiguous submission remains
charged and `unknown` because the provider may have accepted it; an administrator
must reconcile it without submitting again. Unknown tasks do not occupy the
ordinary active-generation queue. After independently proving that the provider
did not create a task, an administrator may use the authenticated reject action;
it records the operator and reason, marks the task failed and refunds exactly
once. Kling 4 stays outside the generic watchdog refund path so the two
settlement mechanisms cannot race.

Telegram and the Mini App show the payable price to ordinary users and the
administrator exemption separately. An ordinary Telegram prompt first freezes
and displays the quote, then requires an explicit **Подтвердить и создать**
action before any debit or provider request. Tasks and recipes remain
owner-private; publication/prompt actions are disabled. Integer rates remain
editable as decimal rates in the existing admin price screen.

### Telegram duration controls

Кнопки длительности «−1с», «+1с» и текущего значения обновляют существующую карточку и стоимость через editMessageText. Новое сообщение не отправляется, в том числе при достижении границ длительности или неизменном значении.

### Пользовательские сообщения

Telegram и форма генерации Mini App показывают пользовательскую цену и понятные статусы. Закупочные расходы, credits, сырые статусы, формы ручной привязки провайдера и JSON-настройки скрыты из генерационного интерфейса. Технические данные остаются в backend и логах; API диагностики и конфигурации сохраняются.

Уточнение Игоря: внутренние ID задач сохраняются в сообщениях запуска, истории, карточке задачи, результатах Telegram и Mini App. Расходы провайдера скрыты.
