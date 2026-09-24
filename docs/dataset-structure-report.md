# 外部数据集结构报告

> 由 `data/external/inspect_datasets.mjs` 自动生成于 2026-09-19 13:50
> 原始文件位于 `data/external/`，本报告只做结构摘要，不复制全量数据。

---

## `apigen_mt_5k.json`  (121.8 MB)

- 顶层类型: **Array**，记录数: **5,000**
- 解析耗时: 367 ms

### 字段结构（第 1 条记录）

| 字段 | 类型 | 示例（截断） |
|---|---|---|
| `conversations` | Array(10) | `{"from":"human","value":"Hello, I have a request regarding a past flight reservation, 0U4NPP, from PHL to DEN. I was wondering if I could still cancel it due to …(+20字符)` |
| `tools` | string | `[{"name": "book_reservation", "description": "Book a reservation.", "parameters": {"type": "object", "properties": {"user_id": {"type": "string", "description": …(+8502字符)` |
| `system` | string | `# Airline Agent Policy The current time is 2024-05-15 15:00:00 EST.  As an airline agent, you can help users book, modify, or cancel flight reservations. - Befo …(+5975字符)` |

### 对话轮次结构

角色序列: `human` → `gpt` → `human` → `function_call` → `observation` → `function_call` → `observation` → `gpt` → `human` → `gpt`

- **human** (153 字符): Hello, I have a request regarding a past flight reservation, 0U4NPP, from PHL to DEN. I was wondering if I could still cancel it due to personal reasons.
- **gpt** (269 字符): To assist you with the cancellation request, I need to verify a few details: ⏎  ⏎ 1. Your user ID. ⏎ 2. The reason for cancellation (change of plan, airline cancelled flight, or other reasons). ⏎  ⏎ Please provide this information so I can check the eligibility for cancellation.
- **human** (231 字符): Sure. My user ID is amelia_rossi_1651. The reason for the cancellation request is personal. I understand if it's an unusual request as the flights have already landed, but I thought it was worth checking if there's any flexibility.
- **function_call** (78 字符): {"name": "get_reservation_details", "arguments": {"reservation_id": "0U4NPP"}}
- **observation** (839 字符): {"reservation_id": "0U4NPP", "user_id": "amelia_rossi_1651", "origin": "PHL", "destination": "DEN", "flight_type": "round_trip", "cabin": "economy", "flights": [{"origin": "PHL", "destination": "DEN", "flight_number": "HAT076", "date": "2024-05-09", "price": 143}, {"origin": "DEN", "destination": "P …(+539字符)
- **function_call** (530 字符): {"name": "think", "arguments": {"thought": "The reservation 0U4NPP is for a round trip from PHL to DEN, with flights on May 9 and May 13, 2024. The flights have already been completed, and the user is requesting a cancellation for personal reasons. According to the policy, cancellations cannot be pr …(+230字符)
- …共 10 轮

### 统计（抽样 2,000 条）

- 平均每条 JSON 长度: **23162** 字符；最长: 57,626
- 含中文的记录: **0/2000** (0.0%)

---

## `glaive_function_calling_v2.json`  (258.6 MB)

- 顶层类型: **Array**，记录数: **112,960**
- 解析耗时: 667 ms

### 字段结构（第 1 条记录）

| 字段 | 类型 | 示例（截断） |
|---|---|---|
| `system` | string | `SYSTEM: You are a helpful assistant with access to the following functions. Use them if required - {     "name": "get_exchange_rate",     "description": "Get th …(+504字符)` |
| `chat` | string | `USER: Can you book a flight for me from New York to London?   ASSISTANT: I'm sorry, but I don't have the capability to book flights. My current function allows  …(+114字符)` |

### 对话轮次结构

角色序列: `USER` → `ASSISTANT`

- **USER** (55 字符): Can you book a flight for me from New York to London? ⏎  ⏎ 
- **ASSISTANT** (201 字符): I'm sorry, but I don't have the capability to book flights. My current function allows me to get the exchange rate between two currencies. If you need help with that, feel free to ask! <|endoftext|> ⏎  ⏎  ⏎ 

### 统计（抽样 2,000 条）

- 平均每条 JSON 长度: **2405** 字符；最长: 14,030
- 含中文的记录: **0/2000** (0.0%)

---

## `hermes_func-calling-singleturn.json`  (17.0 MB)

- 顶层类型: **Array**，记录数: **1,893**
- 解析耗时: 33 ms

### 字段结构（第 1 条记录）

| 字段 | 类型 | 示例（截断） |
|---|---|---|
| `id` | string | `85f6c398-69c7-4df2-aed1-29d614a93a26` |
| `conversations` | Array(3) | `{"from":"system","value":"You are a function calling AI model. You are provided with function signatures within <tools> </tools> XML tags. You may call one or m …(+3056字符)` |
| `tools` | string | `[{"type": "function", "function": {"name": "get_camera_live_feed", "description": "Retrieves the live feed from a specified security camera.", "parameters": {"t …(+2278字符)` |
| `category` | string | `IoT and Home Automation` |
| `subcategory` | string | `Security Camera Management` |
| `task` | string | `View and Manage Security Camera Feeds` |

### 对话轮次结构

角色序列: `system` → `human` → `gpt`

- **system** (2918 字符): You are a function calling AI model. You are provided with function signatures within <tools> </tools> XML tags. You may call one or more functions to assist with the user query. Don't make assumptions about what values to plug into functions. ⏎ <tools> ⏎ [{"type": "function", "function": {"name": "get_ …(+2618字符)
- **human** (1670 字符): I've recently installed a new security system at my home, and I want to ensure everything is functioning as it should. Specifically, I'd like to start by checking the live feed from the camera located at the front door to monitor any activity. The camera has a unique identifier, which I've already c …(+1370字符)
- **gpt** (414 字符): <tool_call> ⏎ {"name": "get_camera_live_feed", "arguments": {"camera_id": "front_door", "stream_quality": "1080p"}} ⏎ </tool_call> ⏎ <tool_call> ⏎ {"name": "record_camera_feed", "arguments": {"camera_id": "front_door", "duration": 30}} ⏎ </tool_call> ⏎ <tool_call> ⏎ {"name": "get_recorded_feed", "arguments": {"ca …(+114字符)

### 统计（抽样 1,893 条）

- 平均每条 JSON 长度: **9375** 字符；最长: 18,000
- 含中文的记录: **0/1893** (0.0%)

---

## `hermes_func-calling.json`  (19.6 MB)

- 顶层类型: **Array**，记录数: **1,893**
- 解析耗时: 38 ms

### 字段结构（第 1 条记录）

| 字段 | 类型 | 示例（截断） |
|---|---|---|
| `id` | string | `82088305-310b-45cb-ac76-ab273503b5cd` |
| `conversations` | Array(5) | `{"from":"system","value":"You are a function calling AI model. You are provided with function signatures within <tools> </tools> XML tags. You may call one or m …(+3056字符)` |
| `tools` | string | `[{"type": "function", "function": {"name": "get_camera_live_feed", "description": "Retrieves the live feed from a specified security camera.", "parameters": {"t …(+2278字符)` |
| `category` | string | `IoT and Home Automation` |
| `subcategory` | string | `Security Camera Management` |
| `task` | string | `View and Manage Security Camera Feeds` |

### 对话轮次结构

角色序列: `system` → `human` → `gpt` → `tool` → `gpt`

- **system** (2918 字符): You are a function calling AI model. You are provided with function signatures within <tools> </tools> XML tags. You may call one or more functions to assist with the user query. Don't make assumptions about what values to plug into functions. ⏎ <tools> ⏎ [{"type": "function", "function": {"name": "get_ …(+2618字符)
- **human** (1670 字符): I've recently installed a new security system at my home, and I want to ensure everything is functioning as it should. Specifically, I'd like to start by checking the live feed from the camera located at the front door to monitor any activity. The camera has a unique identifier, which I've already c …(+1370字符)
- **gpt** (414 字符): <tool_call> ⏎ {"name": "get_camera_live_feed", "arguments": {"camera_id": "front_door", "stream_quality": "1080p"}} ⏎ </tool_call> ⏎ <tool_call> ⏎ {"name": "record_camera_feed", "arguments": {"camera_id": "front_door", "duration": 30}} ⏎ </tool_call> ⏎ <tool_call> ⏎ {"name": "get_recorded_feed", "arguments": {"ca …(+114字符)
- **tool** (741 字符): <tool_response> ⏎ {"name": "get_camera_live_feed", "content": {"camera_id": "front_door", "stream_quality": "1080p", "live_feed_url": "https://homecam.example.com/live/front_door_1080p"}} ⏎ </tool_response> ⏎ <tool_response> ⏎ {"name": "record_camera_feed", "content": {"camera_id": "front_door", "duration": …(+441字符)
- **gpt** (1135 字符): I have successfully executed all the requested functions for your home security cameras. Here are the results: ⏎  ⏎ 1. **Live Feed from "front_door" Camera:** ⏎    - You can view the high-definition 1080p live feed from your front door camera at the [following link](https://homecam.example.com/live/front_ …(+835字符)

### 统计（抽样 1,893 条）

- 平均每条 JSON 长度: **10828** 字符；最长: 18,000
- 含中文的记录: **2/1893** (0.1%)

---

## `hermes_glaive-function-calling-5k.json`  (19.5 MB)

- 顶层类型: **Array**，记录数: **5,209**
- 解析耗时: 38 ms

### 字段结构（第 1 条记录）

| 字段 | 类型 | 示例（截断） |
|---|---|---|
| `id` | string | `6a627c93-0c43-4a04-9432-7d6063f87617` |
| `conversations` | Array(11) | `{"from":"system","value":"You are a function calling AI model. You are provided with function signatures within <tools></tools> XML tags.You may call one or mor …(+1192字符)` |
| `tools` | string | `[{"type": "function", "function": {"name": "get_stock_price", "description": "Get the current stock price of a company", "parameters": {"type": "object", "prope …(+362字符)` |
| `category` | string | `Stocks and Orders` |
| `subcategory` | string | `Get Stock Price` |
| `task` | string | `Stock Price Inquiries` |
| `source` | string | `Glaive` |

### 对话轮次结构

角色序列: `system` → `human` → `gpt` → `tool` → `gpt` → `human` → `gpt` → `tool` → `gpt` → `human` → `gpt`

- **system** (1247 字符): You are a function calling AI model. You are provided with function signatures within <tools></tools> XML tags.You may call one or more functions to assist with the user query. Don't make assumptions about what values to plug into functions.Here are the available tools:<tools> ⏎ [{"type": "function",  …(+947字符)
- **human** (53 字符): Hi, can you tell me the current stock price of Apple?
- **gpt** (87 字符): <tool_call> ⏎ {"name": "get_stock_price", "arguments": {"company": "Apple"}} ⏎ </tool_call>
- **tool** (99 字符): <tool_response> ⏎ {"name": "get_stock_price", "content": {"stock_price": "$150.75"}} ⏎ </tool_response>
- **gpt** (44 字符): The current stock price of Apple is $150.75.
- **human** (65 字符): That's great. Can you also tell me the stock price for Microsoft?
- …共 11 轮

### 统计（抽样 2,000 条）

- 平均每条 JSON 长度: **3764** 字符；最长: 9,767
- 含中文的记录: **0/2000** (0.0%)

---

## `hermes_json-mode-singleturn.json`  (2.8 MB)

- 顶层类型: **Array**，记录数: **1,241**
- 解析耗时: 8 ms

### 字段结构（第 1 条记录）

| 字段 | 类型 | 示例（截断） |
|---|---|---|
| `id` | string | `55a58ac1-2166-4c73-be0e-0f74f349f3a2` |
| `conversations` | Array(3) | `{"from":"system","value":"You are a helpful assistant that answers in JSON. Here's the json schema you must adhere to:\n<schema>\n{\"title\": \"PatentPortfolio\ …(+572字符)` |
| `category` | string | `Pharmaceuticals, Biotechnology & Life Sciences` |
| `subcategory` | string | `Biotechnology` |
| `schema` | string | `{"title": "PatentPortfolio", "type": "object", "properties": {"patentID": {"title": "Patent ID", "type": "string"}, "title": {"title": "Title", "type": "string" …(+341字符)` |
| `__index_level_0__` | number | `0` |

### 对话轮次结构

角色序列: `system` → `human` → `gpt`

- **system** (614 字符): You are a helpful assistant that answers in JSON. Here's the json schema you must adhere to: ⏎ <schema> ⏎ {"title": "PatentPortfolio", "type": "object", "properties": {"patentID": {"title": "Patent ID", "type": "string"}, "title": {"title": "Title", "type": "string"}, "filingDate": {"title": "Filing Dat …(+314字符)
- **human** (472 字符): Please create a JSON object for our biotech company's patent portfolio. We need to include the following details for each patent: the unique patent ID, which for one of our patents is 'US9876543B2', the title of the invention, in this case, 'CRISPR Gene Editing Delivery System', the date when the pa …(+172字符)
- **gpt** (172 字符): {"patentID": "US9876543B2", "title": "CRISPR Gene Editing Delivery System", "filingDate": "2019-06-15", "patentStatus": "Granted", "technologyField": "Genetic Engineering"}

### 统计（抽样 1,241 条）

- 平均每条 JSON 长度: **2355** 字符；最长: 5,189
- 含中文的记录: **0/1241** (0.0%)

---

## `toolace_data.json`  (35.4 MB)

- 顶层类型: **Array**，记录数: **11,300**
- 解析耗时: 94 ms

### 字段结构（第 1 条记录）

| 字段 | 类型 | 示例（截断） |
|---|---|---|
| `system` | string | `You are an expert in composing functions. You are given a question and a set of possible functions.  Based on the question, you will need to make one or more fu …(+3856字符)` |
| `conversations` | Array(10) | `{"from":"user","value":"I'm considering investing and I'd like to know what's happening in the market right now. Could you get me the top market trends in the U …(+4字符)` |

### 对话轮次结构

角色序列: `user` → `assistant` → `tool` → `assistant` → `user` → `assistant` → `user` → `assistant` → `user` → `assistant`

- **user** (138 字符): I'm considering investing and I'd like to know what's happening in the market right now. Could you get me the top market trends in the US?
- **assistant** (62 字符): [Market Trends API(trend_type="MARKET_INDEXES", country="us")]
- **tool** (784 字符): [{"name": "Market Trends API", "results": {"trends": [{"name": "S&P 500", "description": "Standard & Poor's 500 Index is a market-capitalization-weighted index of the 500 largest U.S. publicly traded companies.", "data": {"current_value": "4172.80", "percentage_change": "+0.68%"}}, {"name": "DOW J", …(+484字符)
- **assistant** (793 字符): Here are the top Market Trends in the US right now: ⏎  ⏎ 1. **S&P 500**: The Standard & Poor's 500 Index is a market-capitalization-weighted index of the 500 largest U.S. publicly traded companies. Its current value is 4172.80 with a percentage change of +0.68%. ⏎  ⏎ 2. **DOW J**: The Dow Jones Industrial A …(+493字符)
- **user** (92 字符): Could you explain what SEC filings are and how they might be useful for an investor like me?
- **assistant** (2001 字符): Sure, SEC filings refer to official documents that are submitted by publicly traded companies to the U.S. Securities and Exchange Commission (SEC). These documents provide valuable information about a company's financial performance, its management team, ownership, key business operations, market co …(+1701字符)
- …共 10 轮

### 统计（抽样 2,000 条）

- 平均每条 JSON 长度: **4432** 字符；最长: 17,578
- 含中文的记录: **4/2000** (0.2%)

---

## `xlam60k.json`  (91.7 MB)

- 顶层类型: **Array**，记录数: **60,000**
- 解析耗时: 200 ms

### 字段结构（第 1 条记录）

| 字段 | 类型 | 示例（截断） |
|---|---|---|
| `id` | number | `0` |
| `query` | string | `Where can I find live giveaways for beta access and games?` |
| `answers` | string | `[{"name": "live_giveaways_by_type", "arguments": {"type": "beta"}}, {"name": "live_giveaways_by_type", "arguments": {"type": "game"}}]` |
| `tools` | string | `[{"name": "live_giveaways_by_type", "description": "Retrieve live giveaways from the GamerPower API based on the specified type.", "parameters": {"type": {"desc …(+109字符)` |

### 完整样例（第 1 条，截断）

```json
{
  "id": 0,
  "query": "Where can I find live giveaways for beta access and games?",
  "answers": "[{\"name\": \"live_giveaways_by_type\", \"arguments\": {\"type\": \"beta\"}}, {\"name\": \"live_giveaways_by_type\", \"arguments\": {\"type\": \"game\"}}]",
  "tools": "[{\"name\": \"live_giveaways_by_type\", \"description\": \"Retrieve live giveaways from the GamerPower API based on the specified type.\", \"parameters\": {\"type\": {\"description\": \"The type of giveaways to retrieve (e.g., game, loot, beta).\", \"type\": \"str\", \"default\": \"game\"}}}]"
}
```

### 统计（抽样 2,000 条）

- 平均每条 JSON 长度: **1623** 字符；最长: 6,530
- 含中文的记录: **0/2000** (0.0%)

---

## `xlam60k_parsed.parquet`  (24.9 MB)

Parquet 格式（列式存储，需 pyarrow/pandas 读取）。用以下命令查看：

```python
import pandas as pd
df = pd.read_parquet(r"D:\Projects\qwen-local-tool-agent\data\external\xlam60k_parsed.parquet")
print(df.shape, df.columns.tolist())
print(df.iloc[0].to_dict())
```

---

## `xlam_irrelevance_7.5k.json`  (7.4 MB)

- 顶层类型: **Array**，记录数: **7,500**
- 解析耗时: 20 ms

### 字段结构（第 1 条记录）

| 字段 | 类型 | 示例（截断） |
|---|---|---|
| `query` | string | `Who was the runner-up in the NCAA Final Four for the year 2019?` |
| `tools` | string | `[{"name": "get_general_game_information", "description": "Retrieves the most general information for a specified NBA game, including away team, home team, game  …(+959字符)` |
| `answers` | string | `[]` |

### 完整样例（第 1 条，截断）

```json
{
  "query": "Who was the runner-up in the NCAA Final Four for the year 2019?",
  "tools": "[{\"name\": \"get_general_game_information\", \"description\": \"Retrieves the most general information for a specified NBA game, including away team, home team, game date, and game start time. All times are in Eastern (ET) time zone.\", \"parameters\": {\"gameid\": {\"description\": \"The unique identifier for the NBA game. This can be retrieved from calls like `getNBAGamesForDate` or `getNBATeamSchedule`.\", \"type\": \"str\", \"default\": \"20221202_CHI@GS\"}}}, {\"name\": \"raceresult\", \"description\": \"Fetches the result for a specific Formula 1 race in a given season.\", \"parameters\": {\"round\": {\"description\": \"The round number or name of the race in the F1 season.\", \"type\": \"str\", \"default\": \"round\"}, \"year\": {\"description\": \"The year of the F1 season.\", \"type\": \"str\", \"default\": \"year\"}}}, {\"name\": \"v4_sports\", \"description\": \"Returns a list of available sports and tournaments using the RapidAPI Odds API.\", \"parameters\": {\"all\": {\"description\": \"When True, includes all available sports. When excluded or False, only shows recently updated (in-season) sports. Default is None.\", \"type\": \"bool, optional\", \"default\": \"true\"}}}]",
  "answers": "[]"
}
```

### 统计（抽样 2,000 条）

- 平均每条 JSON 长度: **1019** 字符；最长: 5,260
- 含中文的记录: **2/2000** (0.1%)
