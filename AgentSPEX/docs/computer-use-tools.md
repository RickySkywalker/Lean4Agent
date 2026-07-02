# Computer Use Tools

The implementation of these tools are based on [WebGym](https://github.com/microsoft/webgym).

The sandbox supports visual browser interaction via **Set-of-Marks (SoM)** — an annotated screenshot showing numbered colored boxes over every interactive element, alongside an accessibility tree listing each element's text and tag. The LLM picks elements by number rather than estimating pixel coordinates.

---

## Workflow

```
browser_navigate(url)          # navigate + capture SoM screenshot (default)
  → annotated screenshot injected into LLM context
  → accessibility tree returned as text

browser_click_element(N)       # click element N from the SoM map
browser_type(text)             # type into the focused element
browser_key("Enter")           # press a key
browser_scroll("down")         # scroll the page
```

**Example workflow YAML:**

```yaml
config:
  model: gpt-5.4
  enabled_tools:
    - browser_navigate      # navigate + get SoM screenshot
    - browser_click_element # click any element by number
    - browser_type          # type text into focused element
    - browser_key           # Enter, Tab, Escape, arrow keys, shortcuts
    - browser_scroll        # reveal off-screen content
context:
  vision_auto_screenshot: true
  interaction_mode: set_of_marks
```

## Browser Tools

| Tool | Description |
|---|---|
| `browser_navigate(url, limit, screenshot, som)` | Navigate to a URL. Returns page summary, actionable elements, and a SoM-annotated screenshot. `som=True` by default. |
| `browser_action(action_id, input_text, limit, screenshot, som)` | Interact with an element by its `target_id` from the actions list. |
| `browser_screenshot(full_page)` | Capture a plain screenshot of the current page. |
| `browser_click_element(element_number)` | Click a numbered element from the most recent SoM screenshot. |
| `browser_type(text, press_enter)` | Type text into the currently focused element. Call `browser_click_element` first to focus it. |
| `browser_key(key)` | Press a key or shortcut, e.g. `"Enter"`, `"Tab"`, `"Control+a"`. Uses Playwright key names. |
| `browser_scroll(direction, amount)` | Scroll the page `"up"` or `"down"` by `amount` pixels (default 300). |
| `analyze_screenshot(file_path, query)` | Send a screenshot to the vision model with a question and get a text answer. Accepts a vpath like `/shots/shot-X.png`. |

---


## Sliding Window

Screenshots accumulate quickly in long sessions. The pipeline keeps only the last N screenshots as actual images; older ones are replaced with a text label (`[Screenshot from browser_navigate]`).

```yaml
context:
  vision_auto_screenshot: true
  vision_max_history: 4   # default: 4
```

---

## Action Format

When `interaction_mode: set_of_marks` is set, this is appended to the system prompt automatically:

```
- Click [N]
- Type [N] [text]
- Hover [N]
- Scroll [N or WINDOW] [up or down]
- GoBack
- Wait
```
