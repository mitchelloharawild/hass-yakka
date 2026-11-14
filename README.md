# Yakka for Home Assistant

A Home Assistant integration for [Yakka](https://github.com/mitchelloharawild/yakka),
the account-less household chore tracker. See what's due, whose turn it is,
and tick chores off from dashboards, automations and voice. Optionally,
Yakka's signed webhooks make updates instant.

## What you get

Each Yakka group you add is a device in Home Assistant, with:

| Entity | What it shows |
|---|---|
| `todo.<group>_chores` | Every chore as a to-do item. Due and overdue chores are open; ticking one completes it in Yakka, and unticking a completed one undoes it. Recurring chores reopen when they're next due. |
| `sensor.<group>_due_chores` | How many chores are due or overdue, with their titles as an attribute |
| `sensor.<group>_overdue_chores` | How many chores are overdue |

And for each chore:

| Entity | What it shows |
|---|---|
| `sensor.<group>_<chore>_status` | `upcoming`, `due`, `overdue`, `done` or `unscheduled`, with schedule details as attributes |
| `sensor.<group>_<chore>_next_due` | When it's next due |
| `sensor.<group>_<chore>_last_completed` | When it was last done, and by whom |
| `sensor.<group>_<chore>_whose_turn` | The current assignee (fixed or round-robin chores) |
| `button.<group>_complete_<chore>` | Ticks the chore off |

Chores added in Yakka show up automatically. Archived or deleted chores are removed.

## Automations

The automation editor's add dialogs have two views, and Yakka shows up in both.

### By target

Pick the chores first, then what should happen. Expand the group's device and
pick one of a chore's entities (any of them stands for that chore), or pick
the device itself for all of its chores:

| | |
|---|---|
| **Triggers** | Chore completed, chore completion undone, chore became due, chore became overdue. |
| **Conditions** | Chore is due (or overdue), chore is overdue, chore isn't due, and chore completed by a given member (name or id). With several chores targeted, choose whether any or all must match. |
| **Actions** | Complete chore and Undo completion. These need exactly one chore's entity as the target, so a device target won't complete every chore at once. |

To act only on one member's completions, pair the trigger with the
**Chore completed by** condition:

```yaml
triggers:
  - trigger: yakka.chore_completed
    target:
      entity_id: sensor.home_bins_status
conditions:
  - condition: yakka.chore_completed_by
    target:
      entity_id: sensor.home_bins_status
    options:
      member: Sam
```

The trigger's variables are the `yakka_chore_event` data below, e.g.
`{{ trigger.member }}`.

### By type → Device

Pick the group's device and you get:

| | |
|---|---|
| **Triggers** | A chore was completed (optionally by a given member), a completion was undone, a chore became due, a chore became overdue. Each can be narrowed to one chore, chosen from the group's chores. |
| **Conditions** | A chore is due (or overdue), is overdue, or isn't due. |
| **Actions** | Complete a chore (optionally as a given member, with a note), or undo its last completion. |

The triggers work out what changed by comparing each update with the last, so
they work with polling alone; [webhooks](#instant-updates-and-events-optional)
make them fire within seconds rather than at the next poll. A chore that goes
straight from upcoming to overdue between updates fires both "became due" and
"became overdue". If a chore is completed and undone between two polls,
neither fires.

They're built on the `yakka_chore_event` event, which you can also use
directly:

```yaml
event_type: yakka_chore_event
data:
  config_entry_id: "…"
  device_id: "…"          # the group's device
  chore_id: "cm…"
  chore: "Bins"
  type: completed         # completed, undone, due, overdue
  completion_id: "…"      # completed and undone only
  member_id: "…"
  member: "Alex"
```

### Who gets credit

A chore completed from Home Assistant (button, to-do list or action) is
recorded as:

1. the member linked to the Home Assistant user who did it, if you've linked
   them in the options (see below);
2. otherwise the Yakka member whose name matches that user's name (ignoring
   case), if "Match Home Assistant users to members" is on (the default);
3. otherwise the default member chosen in the options;
4. otherwise "Automation".

To link users, turn on **Choose a member for each Home Assistant user** in the
options. You'll then get a dropdown for each Home Assistant user, with these
choices:

- **Match by name**: the default; uses step 2.
- **Record as the default**: skips name matching.
- A specific member.

Automations and scripts usually don't run as a user, so they get the default
member.

The `yakka.complete_chore` action can also name the member directly.

## Installation

### Marketplace (Home Assistant 2026.11 and later)

1. Go to **Settings** → **Marketplace**, select **Add from link**, and enter
   `https://github.com/mitchelloharawild/hass-yakka`.
2. Open **Yakka**, select **Install**, and restart Home Assistant when asked.

Yakka is added as a custom repository. The Marketplace only checks custom
repositories for updates when you've connected GitHub, and then only every
48 hours. To connect GitHub, open the **Marketplace** integration's ⋮ menu and
select **Reconfigure**.

### HACS (before Home Assistant 2026.11)

1. In HACS, open the menu → **Custom repositories**, and add
   `https://github.com/mitchelloharawild/hass-yakka` as an **Integration**.
2. Install **Yakka** and restart Home Assistant.

### Manually

Copy `custom_components/yakka` into your Home Assistant `config/custom_components/`
folder and restart.

The Yakka logo appears in Home Assistant 2026.3 and later. Earlier versions
show a placeholder icon, but everything else works.

## Setup

1. In Yakka, open your group and go to **Integrations**. Create an **API token**
   and copy it (it's shown once).
2. In Home Assistant, go to **Settings → Devices & services → Add integration → Yakka**.
3. Paste the group's link (e.g. `https://yakka.nectric.com.au/groups/…`) and the token.

Works with the public instance and with self-hosted ones, including those
served from a subpath.

## Options

- **Record completions as**: the default member for completions from Home Assistant.
- **Match Home Assistant users to members** and **Choose a member for each
  Home Assistant user**: see [Who gets credit](#who-gets-credit).
- **Update interval**: how often to poll Yakka (default 5 minutes).
- **Receive Yakka webhooks**: see below.

## Instant updates and events (optional)

Polling is enough for most dashboards. For instant updates, and to trigger
automations on Yakka events, turn on **Receive Yakka webhooks** in the options:

1. Home Assistant shows a webhook URL. In Yakka's **Integrations** page, add an
   outbound webhook with that URL and pick the events you want.
2. Copy the webhook's signing secret (`whsec_…`) back into Home Assistant.

Yakka must be able to reach the URL. A self-hosted Yakka on your LAN can use
the local address; the public instance needs your external URL (e.g. Nabu
Casa). Every request's signature and timestamp are checked, and anything that
fails is rejected.

Each verified event triggers a refresh (and so the triggers above)
and fires Yakka's raw event as a `yakka_event` on the event bus:

```yaml
event_type: yakka_event
data:
  config_entry_id: "…"
  id: evt_…
  type: chore.overdue   # chore.completed, chore.undone, chore.due, chore.overdue, ping
  created_at: "2026-03-01T09:30:00.123Z"
  group: { name: "Home", timezone: "Australia/Melbourne" }
  data: { chore: { id, title, icon }, dueAt, overdueAt, assignee }
```

The `data` payload is Yakka's own: see
[Yakka's webhook docs](https://github.com/mitchelloharawild/yakka/blob/main/docs/API.md#outbound-webhooks).

```yaml
automation:
  - alias: "Flash the hallway when the bins are overdue"
    triggers:
      - trigger: event
        event_type: yakka_event
        event_data:
          type: chore.overdue
    conditions:
      - condition: template
        value_template: "{{ trigger.event.data.data.chore.title == 'Bins' }}"
    actions:
      - action: light.turn_on
        target: { entity_id: light.hallway }
        data: { flash: long }
```

## Actions

### `yakka.complete_chore`

| Field | |
|---|---|
| `chore` | The chore's title (case-insensitive), its Yakka id, or the entity id of any of its entities. Required unless you target one of the chore's entities instead. |
| `member` | Member name or id. Optional; see [Who gets credit](#who-gets-credit). |
| `note` | Optional, up to 500 characters. |
| `completed_at` | Optional; up to 14 days ago. |
| `config_entry_id` | Which group, if you've added more than one. |

Returns `completion_id`, `member`, `deduplicated`, `chore_id`, `status` and
`next_due_at`. Completions within a few minutes of the last one are
deduplicated by Yakka, so automations can safely retry.

```yaml
automation:
  - alias: "Dishwasher finished"
    triggers:
      - trigger: numeric_state
        entity_id: sensor.dishwasher_power
        below: 3
        for: "00:05:00"
    actions:
      - action: yakka.complete_chore
        data:
          chore: Dishes
```

### `yakka.undo_completion`

Takes either a `chore` (as for `complete_chore`, or a target of one of the
chore's entities) to undo its latest completion, or a `completion_id` (from the **Last completed** sensor's
attributes or a `complete_chore` response), plus an optional `config_entry_id`.

## Privacy and security

The group link is the group's access secret. This integration stores it and
the API token in the config entry, keeps them out of entity and device ids,
and redacts them from diagnostics. Revoking the token in Yakka cuts Home
Assistant off immediately; you'll be asked for a new one.

## Development

```sh
uv venv --python 3.13 && uv pip install -r requirements_test.txt
.venv/bin/pytest
```
