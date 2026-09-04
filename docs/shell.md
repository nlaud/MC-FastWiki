# Shell UI & Keyboard Model

The MC-FastWiki shell provides a fast, keyboard-driven interface designed for mid-match draftout lookups. The user operates without touching the mouse, achieving answers in under two seconds.

## Layout & Window Geometry

The shell layout consists of two primary visual layers:

1. **Window Layer**: A CSS Grid that fills the viewport with up to four concurrently open windows (`web/shell/windows.ts`).
2. **Search Layer**: A floating search bar pinned to the bottom of the viewport (`web/shell/searchbar.ts`), displaying an upward suggestion list directly above the input.

### Grid Geometry and Growth Stability

Windows occupy slots `0`, `1`, `2`, and `3`. As windows open, new windows are assigned the lowest free slot index:

| Count | Grid Template | Slot Placement |
| :--- | :--- | :--- |
| **1** | Full viewport (`1fr`) | Occupied slot fills the entire viewport |
| **2** | Side by side (`1fr 1fr` cols, `1fr` row) | Ascending slots: left column, then right column |
| **3** | 2x2 with one empty cell (`1fr 1fr` cols, `1fr 1fr` rows) | Ascending slots: top-left, top-right, bottom-left (bottom-right empty) |
| **4** | Full 2x2 (`1fr 1fr` cols, `1fr 1fr` rows) | Slots 0..3: top-left, top-right, bottom-left, bottom-right |

**Growth stability**: When growing from 3 to 4 windows, the 4th window drops into the empty bottom-right cell. Slots 0, 1, and 2 do not change their quadrant positions.

**Canonical Reflow on Close**: When a window closes, the remaining windows canonically reflow to eliminate dead screen area:
- Closing from 4 windows to 3 reflows into top-left, top-right, and bottom-left.
- Closing from 3 windows to 2 reflows into side-by-side columns.
- Closing from 2 windows to 1 reflows into a single full-screen window.

## Window Focus & Eviction Model

The shell maintains a `focusOrder` array of occupied slot indexes, ordered most-recently-focused first:

- **Focusing a window**: Clicking a window or navigating with keyboard shortcuts moves its slot index to the front of `focusOrder`.
- **Opening a window (< 4 open)**: Takes the lowest free slot and moves it to the front of `focusOrder`.
- **Opening at 4 windows (LRU eviction)**: The search bar is hidden when four windows are open, so new searches cannot occur. However, inline entity links (arriving in Phase 6) can be clicked while four windows are open. When this happens, the shell evicts the least-recently-focused window (`focusOrder[focusOrder.length - 1]`), replacing its content and moving that slot to the front of `focusOrder`. This preserves the window the link was clicked from as well as recently read windows.

## Keyboard Map

The keymap table is defined in `web/shell/keymap.ts` and rendered in the in-app help overlay (`web/shell/help.ts`):

| Key | Action | When |
| :--- | :--- | :--- |
| `a-z`, `0-9`, printable characters | Focus the search bar and insert the character | Bar is visible and unfocused, no modifier held |
| `Up` / `Down` | Move suggestion selection, wrapping at both ends | Suggestion list is non-empty |
| `Up` / `Down` | Scroll the active focused window | Suggestion list is empty and a window is open |
| `Enter` | Open the selected suggestion in a window | A suggestion is selected |
| `Esc` | Clear search query | Always, and only this |
| `Alt+W` | Close the currently focused window | A window is open |
| `Alt+1` to `Alt+4` | Focus the window in slot 1 through 4 | That slot is occupied |
| `Tab` | Focus the next window, wrapping | A window is open |
| `F1` | Toggle the keyboard-map help overlay | Always |
| `Esc` | Dismiss the help overlay | Help overlay is open |

## Window Open Path & Performance Budget

To maintain the budget of rendering a window within 100 ms:
1. **Synchronous Frame Render**: On `Enter`, the window chrome, icon, and title are immediately rendered synchronously from the pre-loaded `IndexEntry` in memory.
2. **Asynchronous Shard Loading**: The entity shard (e.g. `mob-0.json`) is loaded asynchronously via `web/search/load.ts`. An in-memory cache ensures that subsequent lookups from the same shard incur zero network overhead.
3. **Fallback Content**: The window body displays a loading state, followed by the entity kind badge, blurb, and Minecraft Wiki attribution link.
