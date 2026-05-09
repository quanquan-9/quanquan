"""
quanquan 数据库 Schema — PostgreSQL DDL

完整数据库设计：
- 用户表 (users)
- 项目表 (projects)
- 素材表 (materials)
- 音乐库表 (music_tracks)
- 用户偏好表 (user_preferences)
- 反馈表 (feedback)
- 监控事件表 (events)
- QC 报告表 (qc_reports)
"""

SCHEMA_SQL = """
-- ================================================================
-- quanquan Database Schema v2.0
-- PostgreSQL 14+
-- ================================================================

-- 启用扩展
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";       -- 模糊搜索
CREATE EXTENSION IF NOT EXISTS "vector";         -- pgvector (可选)

-- ================================================================
-- 1. 用户表
-- ================================================================
CREATE TABLE IF NOT EXISTS users (
    user_id         VARCHAR(64) PRIMARY KEY,
    username        VARCHAR(128),
    email           VARCHAR(256),
    avatar_url      TEXT,
    role            VARCHAR(32) DEFAULT 'user',   -- user / premium / admin
    status          VARCHAR(16) DEFAULT 'active', -- active / suspended / deleted
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW(),
    last_active_at  TIMESTAMPTZ,
    total_projects  INTEGER DEFAULT 0,
    metadata        JSONB DEFAULT '{}'
);

CREATE INDEX idx_users_email ON users(email) WHERE email IS NOT NULL;
CREATE INDEX idx_users_status ON users(status);


-- ================================================================
-- 2. 项目表
-- ================================================================
CREATE TABLE IF NOT EXISTS projects (
    project_id      VARCHAR(128) PRIMARY KEY,
    user_id         VARCHAR(64) NOT NULL REFERENCES users(user_id),
    name            VARCHAR(256),
    description     TEXT,
    status          VARCHAR(32) DEFAULT 'created',
        -- created / analyzing / planning / dispatching / monitoring
        -- / finalizing / completed / failed / cancelled

    -- 输入配置
    input_type      VARCHAR(32) DEFAULT 'text',   -- text / mixed / audio
    text_prompt     TEXT,
    duration_target_sec INTEGER DEFAULT 180,
    style_tags      TEXT[] DEFAULT '{}',
    references      JSONB DEFAULT '{}',            -- {video_url, image_url, audio_url}

    -- 执行状态
    dag_definition  JSONB,
    node_statuses   JSONB DEFAULT '[]',
    progress        REAL DEFAULT 0.0,              -- 0~1
    replan_count    INTEGER DEFAULT 0,
    director_state  VARCHAR(32),

    -- 产出
    output_draft_path    TEXT,
    output_video_path    TEXT,
    output_notes_path    TEXT,
    output_thumbnail_path TEXT,

    -- 统计
    started_at      TIMESTAMPTZ,
    completed_at    TIMESTAMPTZ,
    elapsed_sec     REAL DEFAULT 0,
    qc_pass_rate    REAL,                           -- 一次成优率
    platforms_exported TEXT[] DEFAULT '{}',          -- [douyin, youtube, ...]

    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW(),

    -- 标记
    is_deleted      BOOLEAN DEFAULT FALSE,
    is_template     BOOLEAN DEFAULT FALSE,
    tags            TEXT[] DEFAULT '{}'
);

CREATE INDEX idx_projects_user ON projects(user_id);
CREATE INDEX idx_projects_status ON projects(status);
CREATE INDEX idx_projects_created ON projects(created_at DESC);
CREATE INDEX idx_projects_tags ON projects USING GIN(tags);
CREATE INDEX idx_projects_style ON projects USING GIN(style_tags);


-- ================================================================
-- 3. 项目 DAG 节点表
-- ================================================================
CREATE TABLE IF NOT EXISTS project_nodes (
    id              SERIAL PRIMARY KEY,
    project_id      VARCHAR(128) NOT NULL REFERENCES projects(project_id),
    node_id         VARCHAR(128) NOT NULL,
    agent           VARCHAR(64) NOT NULL,           -- Director / Scriptwriter / ...
    task            TEXT,
    status          VARCHAR(32) DEFAULT 'pending',  -- pending / running / success / failed
    depends_on      TEXT[] DEFAULT '{}',
    output_key      VARCHAR(128),
    artifact_ref    TEXT,
    started_at      TIMESTAMPTZ,
    completed_at    TIMESTAMPTZ,
    elapsed_sec     REAL,
    retry_count     INTEGER DEFAULT 0,
    error_message   TEXT,
    metadata        JSONB DEFAULT '{}',

    UNIQUE(project_id, node_id)
);

CREATE INDEX idx_nodes_project ON project_nodes(project_id);
CREATE INDEX idx_nodes_agent ON project_nodes(agent);
CREATE INDEX idx_nodes_status ON project_nodes(status);


-- ================================================================
-- 4. 素材表
-- ================================================================
CREATE TABLE IF NOT EXISTS materials (
    material_id     VARCHAR(64) PRIMARY KEY,
    file_path       TEXT NOT NULL,
    media_type      VARCHAR(16) NOT NULL,           -- video / image / audio
    title           VARCHAR(256),
    description     TEXT,

    -- 视频/图片属性
    width           INTEGER DEFAULT 0,
    height          INTEGER DEFAULT 0,
    duration_sec    REAL DEFAULT 0,
    fps             REAL DEFAULT 30,
    codec           VARCHAR(32),

    -- 文件属性
    file_size_bytes BIGINT DEFAULT 0,
    checksum        VARCHAR(64),

    -- 元数据
    tags            TEXT[] DEFAULT '{}',
    license_type    VARCHAR(32) DEFAULT 'unknown',  -- cc0 / commercial / custom
    source_url      TEXT,
    aesthetic_score REAL DEFAULT 0.5,
    embedding       REAL[],                          -- 512-dim CLIP (if pgvector enabled)

    -- 代理
    proxy_path      TEXT,
    proxy_size_bytes BIGINT DEFAULT 0,

    -- 统计
    usage_count     INTEGER DEFAULT 0,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW(),

    is_deleted      BOOLEAN DEFAULT FALSE
);

CREATE INDEX idx_materials_type ON materials(media_type);
CREATE INDEX idx_materials_tags ON materials USING GIN(tags);
CREATE INDEX idx_materials_score ON materials(aesthetic_score DESC);


-- ================================================================
-- 5. 音乐库表
-- ================================================================
CREATE TABLE IF NOT EXISTS music_tracks (
    track_id        VARCHAR(64) PRIMARY KEY,
    file_path       TEXT NOT NULL,
    title           VARCHAR(256),
    artist          VARCHAR(256),
    album           VARCHAR(256),
    duration_sec    REAL DEFAULT 0,
    bpm             REAL DEFAULT 120,
    musical_key     VARCHAR(16),
    genre           VARCHAR(64),
    mood_tags       TEXT[] DEFAULT '{}',
    energy          REAL DEFAULT 0.5,
    valence         REAL DEFAULT 0.5,
    instruments     TEXT[] DEFAULT '{}',
    license_type    VARCHAR(32) DEFAULT 'unknown',
    source_url      TEXT,
    usage_count     INTEGER DEFAULT 0,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_music_mood ON music_tracks USING GIN(mood_tags);
CREATE INDEX idx_music_genre ON music_tracks(genre);
CREATE INDEX idx_music_bpm ON music_tracks(bpm);
CREATE INDEX idx_music_energy ON music_tracks(energy);


-- ================================================================
-- 6. 用户偏好表 (JSONB 灵活模式)
-- ================================================================
CREATE TABLE IF NOT EXISTS user_preferences (
    user_id             VARCHAR(64) PRIMARY KEY REFERENCES users(user_id),
    voice_prefs         JSONB DEFAULT '{}',         -- {"deep_male_03": 0.85, ...}
    transition_prefs    JSONB DEFAULT '{}',         -- {"glitch_dissolve": 0.7, ...}
    filter_prefs        JSONB DEFAULT '{}',         -- {"cyberpunk_purple": 0.9}
    bgm_genre_prefs     JSONB DEFAULT '{}',         -- {"synthwave": 0.8, ...}
    subtitle_style      JSONB DEFAULT '{}',
    global_style_vector REAL[],                      -- 512-dim
    cold_start          BOOLEAN DEFAULT TRUE,
    last_active_time    TIMESTAMPTZ,
    total_projects      INTEGER DEFAULT 0,
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW()
);


-- ================================================================
-- 7. 反馈表
-- ================================================================
CREATE TABLE IF NOT EXISTS feedback (
    id              SERIAL PRIMARY KEY,
    user_id         VARCHAR(64) NOT NULL REFERENCES users(user_id),
    project_id      VARCHAR(128) REFERENCES projects(project_id),
    feedback_type   VARCHAR(32) NOT NULL,           -- like / dislike / override
    target_type     VARCHAR(32),                     -- voice / transition / filter / bgm / subtitle
    node_id         VARCHAR(128),
    old_value       TEXT,
    new_value       TEXT,
    metadata        JSONB DEFAULT '{}',
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_feedback_user ON feedback(user_id);
CREATE INDEX idx_feedback_project ON feedback(project_id);
CREATE INDEX idx_feedback_type ON feedback(feedback_type);


-- ================================================================
-- 8. 监控事件表
-- ================================================================
CREATE TABLE IF NOT EXISTS events (
    id              BIGSERIAL PRIMARY KEY,
    event_type      VARCHAR(64) NOT NULL,
    project_id      VARCHAR(128),
    agent           VARCHAR(64),
    node_id         VARCHAR(128),
    severity        VARCHAR(16) DEFAULT 'info',     -- info / warning / error / critical
    message         TEXT,
    payload         JSONB DEFAULT '{}',
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_events_type ON events(event_type);
CREATE INDEX idx_events_project ON events(project_id);
CREATE INDEX idx_events_created ON events(created_at DESC);
CREATE INDEX idx_events_severity ON events(severity);

-- 自动分区（按月）
-- SELECT create_hypertable('events', 'created_at');  -- TimescaleDB


-- ================================================================
-- 9. QC 报告表
-- ================================================================
CREATE TABLE IF NOT EXISTS qc_reports (
    id              SERIAL PRIMARY KEY,
    project_id      VARCHAR(128) NOT NULL REFERENCES projects(project_id),
    node_id         VARCHAR(128) NOT NULL,
    artifact_ref    TEXT,
    total_checks    INTEGER DEFAULT 0,
    fatal_count     INTEGER DEFAULT 0,
    major_count     INTEGER DEFAULT 0,
    minor_count     INTEGER DEFAULT 0,
    pass_count      INTEGER DEFAULT 0,
    verdict         VARCHAR(16),                     -- PASS / WARN / FAIL
    issues_json     JSONB DEFAULT '[]',
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_qc_project ON qc_reports(project_id);
CREATE INDEX idx_qc_verdict ON qc_reports(verdict);


-- ================================================================
-- 10. 用户记忆锚点表 (pgvector)
-- ================================================================
CREATE TABLE IF NOT EXISTS user_anchors (
    id              SERIAL PRIMARY KEY,
    user_id         VARCHAR(64) NOT NULL,
    anchor_type     VARCHAR(32) NOT NULL,            -- voice / visual / bgm / style
    preference_key  VARCHAR(128),
    embedding       REAL[],
    weight          REAL DEFAULT 1.0,
    last_updated    TIMESTAMPTZ DEFAULT NOW(),
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_anchors_user ON user_anchors(user_id);
CREATE INDEX idx_anchors_type ON user_anchors(anchor_type);


-- ================================================================
-- 视图：项目仪表盘
-- ================================================================
CREATE OR REPLACE VIEW v_project_dashboard AS
SELECT
    p.user_id,
    COUNT(*) FILTER (WHERE p.status = 'completed') AS completed,
    COUNT(*) FILTER (WHERE p.status IN ('monitoring', 'dispatching', 'analyzing')) AS active,
    COUNT(*) FILTER (WHERE p.status = 'failed') AS failed,
    AVG(p.elapsed_sec) FILTER (WHERE p.status = 'completed') AS avg_duration_sec,
    AVG(p.qc_pass_rate) FILTER (WHERE p.status = 'completed') AS avg_qc_pass_rate,
    SUM(p.replan_count) AS total_replans
FROM projects p
WHERE p.is_deleted = FALSE
GROUP BY p.user_id;


-- ================================================================
-- 视图：用户偏好摘要
-- ================================================================
CREATE OR REPLACE VIEW v_user_pref_summary AS
SELECT
    up.user_id,
    u.username,
    (SELECT key FROM jsonb_each_text(up.voice_prefs) ORDER BY value::numeric DESC LIMIT 1) AS top_voice,
    (SELECT key FROM jsonb_each_text(up.filter_prefs) ORDER BY value::numeric DESC LIMIT 1) AS top_filter,
    (SELECT key FROM jsonb_each_text(up.bgm_genre_prefs) ORDER BY value::numeric DESC LIMIT 1) AS top_bgm_genre,
    up.cold_start,
    up.total_projects,
    up.last_active_time
FROM user_preferences up
JOIN users u ON up.user_id = u.user_id;


-- ================================================================
-- 初始数据
-- ================================================================
INSERT INTO users (user_id, username, role)
VALUES ('system', 'quanquan System', 'admin')
ON CONFLICT (user_id) DO NOTHING;
"""


def get_schema_sql() -> str:
    return SCHEMA_SQL


def generate_migration(
    from_version: str = "1.0.0",
    to_version: str = "2.0.0",
) -> str:
    """生成迁移 SQL"""
    return f"""-- Migration: {from_version} → {to_version}
-- Generated: {__import__('datetime').datetime.utcnow().isoformat()}

-- 新增表 (v2.0)
{SCHEMA_SQL.split('-- ================================================================') [7] if 'project_nodes' in SCHEMA_SQL else ''}
"""
