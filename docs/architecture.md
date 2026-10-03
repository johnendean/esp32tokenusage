# Architecture

The display shows **Current session** and **This week** usage (see [CONTEXT.md](../CONTEXT.md)). There is no daemon on the Mac, and the board never fetches anything. Claude Code decides when to send an update: each time it runs the status line, the Mac pushes the latest numbers to the board over Wi-Fi. Between updates, the board uses its own clock to keep the screen current. [ADR 0001](adr/0001-usage-from-status-line-pushed-over-wifi.md) explains why.

## Components

```mermaid
flowchart LR
    api["Anthropic API"]

    subgraph mac["Mac"]
        cc["Claude Code"]
        wrapper["mac/statusline.sh"]
        ccs["ccstatusline"]
        push["mac/push_usage.py<br/>(detached process)"]
        cache[("$TMPDIR/claude-usage-display.json<br/>last sent values")]
        secrets_mac[/"wifi_secrets.py<br/>DEVICE_HOSTS, DEVICE_TOKEN"/]
    end

    subgraph board["Each board (claude-usage-c6.local, claude-usage-s3.local)"]
        server["HTTP server<br/>POST /usage"]
        state[("State<br/>session, week,<br/>clock offset, UTC offset")]
        loop["Redraw loop<br/>every 30 s or on update"]
        logic["usage.py<br/>reset text, Pace message"]
        lcd["Screen, picked by board.py<br/>C6: ST7789 LCD 320×172 landscape<br/>S3: CO5300 AMOLED 368×448 portrait"]
        wifi["Wi-Fi keeper"]
    end

    api -- "responses carry<br/>rate limit data" --> cc
    cc -- "status line JSON on stdin<br/>(rate_limits.five_hour / seven_day)" --> wrapper
    wrapper -- "same JSON" --> ccs
    ccs -- "status line text" --> cc
    wrapper -- "same JSON" --> push
    push <--> cache
    secrets_mac -.-> push
    push == "HTTP POST to every board<br/>in parallel, X-Token header" ==> server
    server --> state
    state --> loop
    loop --> logic
    loop --> lcd
    wifi -. "keeps the board<br/>on the network" .-> server
```

`usage.py` runs on both machines: on the board to draw the screen, and on the Mac for the unit tests.

The same code runs on the Waveshare ESP32-C6-LCD-1.47 and the ESP32-S3-Touch-AMOLED-1.8. At startup `board.py` reads the chip family, sets up that board's display and returns a layout for its screen; the board then announces itself as `<DEVICE_NAME>-c6.local` or `<DEVICE_NAME>-s3.local`. The Mac sends each update to every host in `DEVICE_HOSTS`, so a board that is switched off does not hold up the others.

## What happens on an update

```mermaid
sequenceDiagram
    autonumber
    participant CC as Claude Code
    participant SL as statusline.sh
    participant P as push_usage.py
    participant CS as ccstatusline
    participant B as Board

    Note over CC: Conversation changes<br/>(debounced 300 ms), or a<br/>rate limit's resets_at passes
    CC->>SL: run with status line JSON
    SL->>P: pipe JSON
    alt no rate_limits, or same values sent < 60 s ago
        P-->>SL: exit, nothing sent
    else new or stale values
        P->>P: fork + setsid (detach)
        P-->>SL: parent exits immediately
        P->>B: POST /usage {now, utc_offset, session, week}
        alt wrong or missing token
            B-->>P: 403
        else valid
            B->>B: store numbers and clock offset, wake redraw
            B-->>P: 204
        end
    end
    SL->>CS: pipe the same JSON
    CS-->>CC: status line text
    Note over CC,B: Claude Code may cancel the wrapper on the next update.<br/>The detached send is unaffected.
```

## What the board draws

The board redraws on each update and every 30 seconds in between, working from the last numbers it received and its own clock.

```mermaid
flowchart TD
    start(["Redraw"]) --> hasdata{"Any update<br/>received since boot?"}
    hasdata -- no --> waiting["Top line: 'Connecting to Wi-Fi...'<br/>or 'Waiting for data' + IP<br/>Bars: --% used"]
    hasdata -- yes --> each["For each window<br/>(Current session, This week)"]
    each --> reset{"Reset time<br/>passed?"}
    reset -- yes --> zero["Bar 0%, reset line blank,<br/>no pace judgement"]
    reset -- no --> bar["Bar + 'N% used' + 'Resets …'<br/>orange, red at 90% or more"]
    bar --> full{"Already<br/>100% used?"}
    full -- yes --> reached["Limit reached"]
    full -- no --> early{"Enough of the window gone?<br/>Session ≥ 30%, Week ≥ 15%"}
    early -- no --> skip["No pace judgement"]
    early -- yes --> project["Projected at reset =<br/>used% ÷ fraction elapsed"]
    project --> state{"Projection"}
    state -- "≤ 80%" --> ok["On track"]
    state -- "80–100%" --> close["Cutting it close"]
    state -- "> 100%" --> limit["Limit ~time"]
    ok & close & limit & reached & skip & zero --> pick["Pace message: whichever judged window<br/>is in more danger (earliest limit first).<br/>If none is in danger, This week when judged.<br/>If neither is judged, the top line is blank."]
    pick --> draw(["Draw top line:<br/>white / orange / red"])
```
