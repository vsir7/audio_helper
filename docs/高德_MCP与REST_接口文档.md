# 高德地图 MCP 与 Web 服务 REST（与本项目相关）

---

## 一、高德 MCP Server（产品能力说明）

**MCP（Model Context Protocol）** 用于 AI 客户端（如 Cursor、自研 Agent）通过标准协议调用地图能力。官方介绍与能力列表见：

- [高德地图 MCP Server 概述](https://lbs.amap.com/api/mcp-server)

文档中列出的能力包括（节选）：地理编码、逆地理编码、路径规划、POI 搜索、距离测量等。

### 接入形态（常见）

- 通过 **Node** 运行官方 MCP 服务（以官网最新说明为准）。
- 部分场景支持 **SSE** 远程连接。

**说明：** MCP 面向「宿主进程 + 标准 MCP 协议」。本仓库 **FastAPI 后端**使用下方 **Web 服务 REST**，与 MCP 背后同类能力对应，便于一条 HTTP 链路完成「两人相遇点」计算。

---

## 二、本项目采用：Web 服务 REST（无场所偏好）

使用 [高德开放平台](https://lbs.amap.com/) 的 **Web 服务 Key**（`AMAP_REST_KEY`），通过 HTTPS GET 调用。

### 1. 地理编码（地址 → 经纬度）

| 项目 | 说明 |
|------|------|
| 文档 | [地理/逆地理编码](https://lbs.amap.com/api/webservice/guide/api/georegeo) |
| URL | `https://restapi.amap.com/v3/geocode/geo`（可配置 `AMAP_GEOCODE_URL`） |
| 参数 | `key`、`address`；可选 `city` |

### 2. 逆地理编码（相遇点坐标 → 可读地址）

| 项目 | 说明 |
|------|------|
| 文档 | 同上（逆地理部分） |
| URL | `https://restapi.amap.com/v3/geocode/regeo`（`AMAP_REGEO_URL`） |
| 参数 | `key`、`location`（`经度,纬度`） |
| 用途 | 将**几何中点**转成 `formatted_address` 等，便于展示「推荐相遇点」文字说明 |

### 3. 距离测量（两人各自到相遇点）

| 项目 | 说明 |
|------|------|
| 文档 | [距离测量](https://lbs.amap.com/api/webservice/guide/api/direction)（路径与距离相关章节，以官网为准） |
| URL | `https://restapi.amap.com/v3/distance`（`AMAP_DISTANCE_URL`） |
| 参数 | `key`、`origins`（`lng,lat|lng,lat` 多起点）、`destination`（相遇点）、`type` |
| `type` 常用值 | **0**：直线距离；**1**：驾车导航距离（国内）；**3**：步行规划距离（仅适合较短距离，见官方限制） |

一次请求中 `origins` 传两人坐标（`|` 分隔），`destination` 为中点，返回的 `results` 顺序与 `origins` 一致，用于填充「第一人 / 第二人到相遇点」路程。

---

## 三、本项目「相遇推荐」逻辑（当前版本）

**不包含**咖啡厅、商场等 **POI 关键词偏好**。流程为：

1. 对两人输入地址各做一次 **地理编码**，得到 `location_a`、`location_b`。
2. 计算 **几何中点** `midpoint`（经纬度分别取平均），作为 **推荐相遇坐标**。
3. 对中点做 **逆地理编码**，得到可读 **位置说明**（如 `formatted_address`）。
4. 调用 **距离测量**，计算两人各自到相遇点的距离（及在支持的模式下返回耗时等字段）。

流水线落盘见 `Storage/*.pipeline.json` 中 `amap_meetup_recommend`；`strategy` 字段为 `midpoint_no_poi_preference`。

每次成功的高德 HTTP 往返还会额外写入 **`Storage/{同录音主文件名}_MCP01.json`**、`_MCP02.json` …（内含脱敏后的请求元数据与完整响应 JSON，便于对照「地图侧」通信；字段说明见文件内 `note`）。

---

## 四、Key 与安全

- 在开放平台创建应用，开通 **Web 服务** Key，写入 `backend/.env` 的 `AMAP_REST_KEY`。
- **勿**把 Key 暴露给前端。

---

## 五、代理行为

请求前 **清除代理相关环境变量**，`httpx` 使用 **`trust_env=False`**。

---

## 六、配置项（`backend/.env`）

见 `backend/.env.example` 中 `AMAP_*`：`AMAP_REST_KEY`、`AMAP_GEOCODE_URL`、`AMAP_REGEO_URL`、`AMAP_DISTANCE_URL`、`AMAP_DISTANCE_TYPE`、`AMAP_TIMEOUT_SECONDS`。
