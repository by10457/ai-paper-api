#!/usr/bin/env bash
set -euo pipefail

# 从仓库 .env 读取本地开发库连接信息，并统一使用 utf8mb4 会话。
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/../../../.." && pwd)"
ENV_FILE="${AI_PAPER_ENV_FILE:-$ROOT_DIR/.env}"

usage() {
  cat <<'EOF'
用法：
  local-mysql.sh status
  local-mysql.sh query <只读 SQL>
  local-mysql.sh schema <table> [table...]
  local-mysql.sh apply <临时增量 SQL>
  local-mysql.sh verify-comments <table> [table...]
EOF
}

read_env_value() {
  local key="$1"
  local value
  value="$(awk -F= -v wanted="$key" '$1 == wanted {sub(/^[^=]*=/, ""); print; exit}' "$ENV_FILE")"
  if [[ "$value" == \"*\" && "$value" == *\" ]]; then
    value="${value:1:${#value}-2}"
  elif [[ "$value" == \'*\' && "$value" == *\' ]]; then
    value="${value:1:${#value}-2}"
  fi
  printf '%s' "$value"
}

if [ ! -f "$ENV_FILE" ]; then
  echo "未找到环境变量文件：$ENV_FILE" >&2
  exit 1
fi

DB_HOST="${MYSQL_HOST:-$(read_env_value MYSQL_HOST)}"
DB_PORT="${MYSQL_PORT:-$(read_env_value MYSQL_PORT)}"
DB_NAME="${MYSQL_DB:-$(read_env_value MYSQL_DB)}"
DB_USER="${MYSQL_USER:-$(read_env_value MYSQL_USER)}"
DB_PASSWORD="${MYSQL_PASSWORD:-$(read_env_value MYSQL_PASSWORD)}"

for required_key in MYSQL_HOST MYSQL_PORT MYSQL_DB MYSQL_USER; do
  case "$required_key" in
    MYSQL_HOST) required_value="$DB_HOST" ;;
    MYSQL_PORT) required_value="$DB_PORT" ;;
    MYSQL_DB) required_value="$DB_NAME" ;;
    MYSQL_USER) required_value="$DB_USER" ;;
  esac
  if [ -z "$required_value" ]; then
    echo "环境变量 $required_key 不能为空。" >&2
    exit 1
  fi
done

case "$DB_HOST" in
  localhost|127.0.0.1) ;;
  *)
    echo "拒绝操作非本地数据库主机：$DB_HOST" >&2
    exit 1
    ;;
esac

if [[ ! "$DB_PORT" =~ ^[0-9]+$ ]]; then
  echo "MYSQL_PORT 必须是数字。" >&2
  exit 1
fi
for value in "$DB_NAME" "$DB_USER"; do
  if [[ ! "$value" =~ ^[A-Za-z0-9_.-]+$ ]]; then
    echo "检测到不安全的数据库连接参数。" >&2
    exit 1
  fi
done

CLIENT_MODE=""
MYSQL_CONTAINER=""

if command -v mysql >/dev/null 2>&1; then
  CLIENT_MODE="host"
elif command -v docker >/dev/null 2>&1; then
  MYSQL_CONTAINER="$(docker ps --filter "publish=$DB_PORT" --format '{{.Names}} {{.Image}}' \
    | awk 'tolower($2) ~ /mysql/ {print $1; exit}')"
  if [ -n "$MYSQL_CONTAINER" ]; then
    CLIENT_MODE="docker"
  fi
fi

if [ -z "$CLIENT_MODE" ]; then
  echo "未找到本机 mysql 客户端，也未找到映射到端口 $DB_PORT 的运行中 MySQL 容器。" >&2
  exit 1
fi

run_mysql() {
  if [ "$CLIENT_MODE" = "host" ]; then
    MYSQL_PWD="$DB_PASSWORD" mysql \
      --protocol=tcp \
      --host="$DB_HOST" \
      --port="$DB_PORT" \
      --user="$DB_USER" \
      --default-character-set=utf8mb4 \
      --show-warnings \
      "$DB_NAME" "$@"
  else
    docker exec -i "$MYSQL_CONTAINER" sh -c '
      db_user="$1"
      db_name="$2"
      shift 2
      if [ "$db_user" = "root" ]; then
        db_password="${MYSQL_ROOT_PASSWORD:-}"
      else
        db_password="${MYSQL_PASSWORD:-}"
      fi
      if [ -z "$db_password" ]; then
        echo "容器中未配置当前数据库用户的密码。" >&2
        exit 1
      fi
      MYSQL_PWD="$db_password" exec mysql \
        --user="$db_user" \
        --default-character-set=utf8mb4 \
        --show-warnings \
        "$db_name" "$@"
    ' sh "$DB_USER" "$DB_NAME" "$@"
  fi
}

status() {
  local connection_text="本机 mysql 客户端"
  if [ "$CLIENT_MODE" = "docker" ]; then
    connection_text="Docker 容器（$MYSQL_CONTAINER，经 127.0.0.1:$DB_PORT 映射）"
  fi
  echo "数据库：$DB_NAME"
  echo "连接方式：$connection_text"
  printf '%s\n' \
    "SELECT VERSION(), DATABASE(), @@character_set_client, @@character_set_connection, @@character_set_results, @@collation_connection;" \
    | run_mysql --batch --skip-column-names
}

validate_table_names() {
  local table
  for table in "$@"; do
    if [[ ! "$table" =~ ^[A-Za-z0-9_]+$ ]]; then
      echo "检测到不安全的表名：$table" >&2
      exit 1
    fi
  done
}

show_schema() {
  if [ "$#" -eq 0 ]; then
    echo "至少需要提供一个表名。" >&2
    exit 1
  fi
  validate_table_names "$@"
  local table
  for table in "$@"; do
    printf 'SHOW CREATE TABLE `%s`;\n' "$table" | run_mysql --batch
  done
}

apply_change() {
  local change_file="$1"
  if [ ! -f "$change_file" ]; then
    echo "未找到 SQL 文件：$change_file" >&2
    exit 1
  fi
  if command -v iconv >/dev/null 2>&1 && ! iconv -f UTF-8 -t UTF-8 "$change_file" >/dev/null; then
    echo "SQL 文件不是有效的 UTF-8 编码：$change_file" >&2
    exit 1
  fi
  if ! grep -Eiq 'SET[[:space:]]+NAMES[[:space:]]+utf8mb4' "$change_file"; then
    echo "SQL 文件必须包含 SET NAMES utf8mb4：$change_file" >&2
    exit 1
  fi

  local destructive_pattern
  destructive_pattern='DROP[[:space:]]+(DATABASE|TABLE|COLUMN)|TRUNCATE([[:space:]]+TABLE)?|RENAME[[:space:]]+TABLE'
  if grep -Eiq "$destructive_pattern" "$change_file" && [ "${ALLOW_DESTRUCTIVE_LOCAL:-0}" != "1" ]; then
    echo "检测到破坏性 SQL；确认数据与恢复方案并取得明确授权后，才可设置 ALLOW_DESTRUCTIVE_LOCAL=1。" >&2
    exit 1
  fi

  status
  run_mysql < "$change_file"
  echo "已将增量 SQL 应用到本地数据库 $DB_NAME：$change_file"
}

verify_comments() {
  if [ "$#" -eq 0 ]; then
    echo "至少需要提供一个表名。" >&2
    exit 1
  fi
  validate_table_names "$@"

  local table
  local in_list=""
  for table in "$@"; do
    in_list+="${in_list:+,}'$table'"
  done

  local found_count
  found_count="$(printf '%s\n' \
    "SELECT COUNT(*) FROM information_schema.TABLES WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME IN ($in_list);" \
    | run_mysql --batch --skip-column-names)"
  if [ "$found_count" != "$#" ]; then
    echo "注释校验失败：请求校验 $# 张表，但数据库中只找到 $found_count 张。" >&2
    exit 1
  fi

  local comments_sql
  comments_sql="
SELECT '表', TABLE_NAME, TABLE_COMMENT
FROM information_schema.TABLES
WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME IN ($in_list)
UNION ALL
SELECT '字段', CONCAT(TABLE_NAME, '.', COLUMN_NAME), COLUMN_COMMENT
FROM information_schema.COLUMNS
WHERE TABLE_SCHEMA = DATABASE()
  AND TABLE_NAME IN ($in_list)
  AND COLUMN_NAME NOT IN ('id', 'created_at', 'updated_at')
ORDER BY 1, 2;"
  printf '%s\n' "$comments_sql" | run_mysql --batch --skip-column-names

  local issues_sql
  issues_sql="
SELECT COUNT(*)
FROM (
  SELECT TABLE_COMMENT AS comment_text
  FROM information_schema.TABLES
  WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME IN ($in_list)
  UNION ALL
  SELECT COLUMN_COMMENT
  FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = DATABASE()
    AND TABLE_NAME IN ($in_list)
    AND COLUMN_NAME NOT IN ('id', 'created_at', 'updated_at')
) comments
WHERE comment_text = '' OR comment_text REGEXP '[ÃÂæåçèé]';"

  local issue_count
  issue_count="$(printf '%s\n' "$issues_sql" | run_mysql --batch --skip-column-names)"
  if [ "$issue_count" != "0" ]; then
    echo "注释校验失败：发现 $issue_count 个空注释或疑似乱码注释。" >&2
    exit 1
  fi
  echo "本地数据库 $DB_NAME 的业务注释校验通过。"
}

command_name="${1:-}"
case "$command_name" in
  status)
    [ "$#" -eq 1 ] || { usage >&2; exit 1; }
    status
    ;;
  query)
    [ "$#" -eq 2 ] || { usage >&2; exit 1; }
    if [[ ! "${2^^}" =~ ^[[:space:]]*(SELECT|SHOW|DESCRIBE|DESC|EXPLAIN)[[:space:]] ]]; then
      echo "query 只允许执行只读查询；数据库变更必须通过 apply 执行 SQL 文件。" >&2
      exit 1
    fi
    printf '%s\n' "$2" | run_mysql --batch
    ;;
  schema)
    shift
    show_schema "$@"
    ;;
  apply)
    [ "$#" -eq 2 ] || { usage >&2; exit 1; }
    apply_change "$2"
    ;;
  verify-comments)
    shift
    verify_comments "$@"
    ;;
  -h|--help|help)
    usage
    ;;
  *)
    usage >&2
    exit 1
    ;;
esac
