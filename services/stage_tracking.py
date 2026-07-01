import logging

from services.db import get_connection

logger = logging.getLogger(__name__)


def update_stage_tracking(
    job_id: str,
    filename: str = None,
    status: str = None,
    current_stage: str = None,
    original_url: str = None,
    preprocessed_url: str = None,
    category: str = None,
    expense_row_id: int = None,
    error_message: str = None,
    completed_stage_num: int = None,
    default_current_stage: str = "stage1_validate",
):
    try:
        conn = get_connection()
        with conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "SELECT 1 FROM stage_tracking WHERE job_id = %s", (job_id,)
                )
                exists = cursor.fetchone()

                if not exists:
                    sql = """
                    INSERT INTO stage_tracking (job_id, filename, status, current_stage, original_url)
                    VALUES (%s, %s, %s, %s, %s)
                    """
                    cursor.execute(
                        sql,
                        (
                            job_id,
                            filename or "unknown",
                            status or "queued",
                            current_stage or default_current_stage,
                            original_url,
                        ),
                    )
                else:
                    updates = []
                    params = []

                    if status:
                        updates.append("status = %s")
                        params.append(status)
                    if current_stage:
                        updates.append("current_stage = %s")
                        params.append(current_stage)
                    if original_url:
                        updates.append("original_url = %s")
                        params.append(original_url)
                    if preprocessed_url:
                        updates.append("preprocessed_url = %s")
                        params.append(preprocessed_url)
                    if category:
                        updates.append("category = %s")
                        params.append(category)
                    if expense_row_id is not None:
                        updates.append("expense_row_id = %s")
                        params.append(expense_row_id)
                    if error_message:
                        updates.append("error_message = %s")
                        params.append(error_message)
                    if completed_stage_num:
                        updates.append(
                            f"stage{completed_stage_num}_completed_at = CURRENT_TIMESTAMP"
                        )

                    if updates:
                        sql = (
                            f"UPDATE stage_tracking SET {', '.join(updates)} "
                            "WHERE job_id = %s"
                        )
                        params.append(job_id)
                        cursor.execute(sql, tuple(params))
            conn.commit()
        conn.close()
    except Exception as e:
        logger.error(
            "[Tracking Error] Failed to update stage_tracking for job %s: %s",
            job_id,
            e,
        )
