# Overlap audit: scene_eval_v1 v1.0.0

26 fixtures, 26 with pixels checked. **0 fail**, 6 warn.

| reference | kind | items | with pixels |
|---|---|---|---|
| train_v1 | training | 821 | 359 |
| portrait_v1 | evaluation | 69 | 69 |

| fixture | split | status | hits | warnings |
|---|---|---|---|---|
| cafe-green-chair-window | heldout | ok | — | — |
| cafe-window-seats-bright | heldout | ok | — | — |
| cafe-piano-bistro | heldout | warn | — | train_v1 same city berlin; train_v1 same city berlin; train_v1 same city berlin (+1) |
| cafe-terrace-occupied | heldout | ok | — | — |
| cafe-orange-chairs-terrace | heldout | ok | — | — |
| storefront-white-facade | heldout | ok | — | — |
| storefront-night-street | heldout | ok | — | — |
| tiled-facade-windows | heldout | ok | — | — |
| white-stairs | heldout | ok | — | — |
| red-shutter-wall | heldout | ok | — | — |
| underground-parking | heldout | ok | — | — |
| office-parking-lot | heldout | ok | — | — |
| school-corridor | heldout | ok | — | — |
| dark-hallway-occupied | heldout | ok | — | — |
| dim-store-aisle-occupied | heldout | ok | — | — |
| desk-corner | heldout | warn | — | train_v1 same city grand rapids |
| fenced-sidewalk | heldout | ok | — | — |
| crowded-sidewalk | heldout | warn | — | train_v1 same city toronto; train_v1 same city toronto; train_v1 same city toronto (+10) |
| subway-platform | heldout | warn | — | train_v1 same city new york; train_v1 same city new york; train_v1 same city new york (+30) |
| kitchen-stools | heldout | warn | — | train_v1 same city boston; train_v1 same city boston |
| dev-cafe-window-tables | dev | ok | — | — |
| dev-shop-shelves | dev | warn | — | train_v1 same city london; train_v1 same city london; train_v1 same city london (+37) |
| dev-beach-stairs | dev | ok | — | — |
| dev-parking-corner | dev | ok | — | — |
| dev-bright-kitchen | dev | ok | — | — |
| dev-open-corridor | dev | ok | — | — |
