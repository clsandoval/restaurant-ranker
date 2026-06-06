# Recipe: Eatigo ✅ verified (Nuxt-SSR payload read; no clickthrough)

Read-only availability via the **Nuxt 3 SSR hydration payload** — NOT a UI clickthrough. Eatigo
embeds the entire ~30-day slot window (every offered time + per-slot discount %) server-side in
`<script id="__NUXT_DATA__">`. No date-picker interaction, no shadow-DOM walk, no API call needed.
This is faster and more complete than clicking through dates one by one.

See `../references/platform-knowledge.md` → Eatigo (party-independent; discount per slot).

## Reservation URL shape
`https://eatigo.com/en/branches/<branchId>`  (branchId is the long numeric id, e.g. `3374213675086`)

## Steps (reads the WHOLE window in one shot — all dates at once)
1. **Open + wait + eval in ONE foreground command** (see Gotchas — daemon contention makes
   separate open/eval calls unreliable; a standalone `open` often leaves the session at
   `about:blank`). Pattern:
   ```bash
   S=lakbai-<slug>
   agent-browser --session $S open "https://eatigo.com/en/branches/<branchId>" >/dev/null 2>&1
   sleep 6
   agent-browser --session $S eval '<extractor>'
   ```
2. The extractor parses `document.getElementById("__NUXT_DATA__").textContent` (a flat-array
   ref-encoded JSON, Nuxt 3 format) and dereferences the `branch-arrival-times_branch-detail_*`
   data entry.
3. That entry = `{start_day, end_day, time_mode, timezone, slots:[{discount, slot:"YYYY-MM-DD HH:MM"}]}`.
4. Group `slots` by date; the offered slots for each target date ARE the availability. STOP.
   **Never** click a slot or proceed to the branch reservation page.

## The extractor (verified, copy-paste)
```javascript
(() => {
  const el = document.getElementById("__NUXT_DATA__");
  if(!el) return JSON.stringify({err:"no __NUXT_DATA__ — page not hydrated; re-open"});
  const arr = JSON.parse(el.textContent);
  function deref(i, depth){
    if(depth>16) return "MAXD";
    const v = arr[i];
    if(v===null||v===undefined) return v;
    if(Array.isArray(v)){
      if(v.length===2 && typeof v[0]==="string" && /Reactive|Ref|Set|Map|EmptyRef/.test(v[0]) && typeof v[1]==="number") return deref(v[1],depth+1);
      return v.map(x=> typeof x==="number" ? deref(x, depth+1) : x);
    }
    if(typeof v==="object"){ const o={}; for(const k in v){ const r=v[k]; o[k]= typeof r==="number"?deref(r,depth+1):r; } return o; }
    return v;
  }
  // The SSR DATA object lives at the index referenced by root.data (arr[1].data).
  // Find the key beginning with "branch-arrival-times_branch-detail" (NOT the
  // "_reservation-attendance-date-picker_" one — that's a pinia/state key, value absent).
  // GOTCHA: the payload contains TWO such keys — a real one (numeric ref >=0) and a later
  // placeholder duplicate whose value is -1. Take the FIRST VALID ref and break, else you
  // keep the -1 placeholder and the extractor returns "no arrival-times slots".
  let ref=null;
  outer:
  for(let i=0;i<arr.length;i++){
    const v=arr[i];
    if(v && typeof v==="object" && !Array.isArray(v)){
      for(const k in v){
        if(typeof k==="string" && k.indexOf("branch-arrival-times_branch-detail")===0
           && typeof v[k]==="number" && v[k]>=0){ ref=v[k]; break outer; }
      }
    }
  }
  const data = ref!=null ? deref(ref,0) : null;
  if(!data || !data.slots) return JSON.stringify({err:"no arrival-times slots found", ref});
  const byDate={};
  for(const s of data.slots){ const [d,t]=s.slot.split(" "); (byDate[d]=byDate[d]||[]).push({time:t,discount:s.discount}); }
  return JSON.stringify({start:data.start_day,end:data.end_day,tz:data.timezone,total:data.slots.length,byDate});
})()
```

## Classification
- Date appears in `byDate` with slots → `available` (one record per slot; carry `discount_pct`).
- Date is **inside** `[start_day, end_day]` but absent from `byDate` → `full` (booked out / no offered times that day).
- Date is **outside** the SSR window (`> end_day`, ~30 days out) → `no-slots` (out of booking window).
- `__NUXT_DATA__` absent / page stuck at `about:blank` → `unresolved` (re-open; daemon contention).
- Cloudflare / stripped page → check `get title`/`get url`; if blocked, CloakBrowser-over-CDP fallback.

## Party dimension
- [x] **party-independent** (probe party 2 only). The arrival-times window does not vary by party
      size; the `_2` suffix on the key is the default headcount. Recording party_size:2 is sufficient.

## Discount semantics
- `discount` is the Eatigo table-discount % for that time slot. Typical pattern: a low baseline
  (e.g. 10%) most slots, with peak-discount slots (commonly 50%) at off-peak times. Capture per slot.

## Gotchas / cases handled (ledger)
- ✅ **The Glass House @ S31 Sukhumvit Hotel** (Bangkok, Phrom Phong, branch `3374213675086`),
  2026-05-30 probe: all 6 target dates (Jun 6/7/10/13/20/24) fully available, 18 slots/day
  10:30–19:00 @30min, 10% baseline + 50% at 13:30 & 17:30. Zero unresolved. tz Asia/Bangkok.
- ⚠️ **Daemon contention / about:blank:** a bare `agent-browser open` frequently returns "Operation
  timed out" AND leaves the session at `about:blank` when prior calls left a stale supervised
  daemon. Fix that WORKED: chain `open` + `sleep 6` + `eval` in a SINGLE foreground bash invocation
  (serialize within one command). Repeated `pkill` of `agent-browser-chrome` is unreliable here —
  processes are supervised/respawn — and is not needed once calls are serialized.
- ✅ The flat-array `__NUXT_DATA__` ref format: two distinct arrival-times keys exist — only
  `branch-arrival-times_branch-detail_*` carries the SSR slot value; the
  `_reservation-attendance-date-picker_*` key is a pinia/state placeholder (value absent → null).

## Open / unverified cases
- ⬜ A genuinely booked-out / closed day (does it drop from `slots` entirely, or appear with an
  empty list / a closed flag?) — confirm `full` vs `no-slots` rendering on a sold-out venue.
- ⬜ Window edge: behaviour for dates beyond `end_day` (assumed `no-slots`).
- ⬜ Multi-meal-period venues: does `time_mode`/headcount id change the key suffix or split windows?
- ⬜ Non-`/en/` locale paths and other Eatigo regions (TH/SG/HK/PH/MY) — confirm same payload shape.
