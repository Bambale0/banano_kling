#!/usr/bin/env python3
"""Add VK error 901 guard to stop retrying delivery to users who blocked the bot."""
import re

with open("vk_bot_lp.py", "r") as f:
    content = f.read()

old_except = '''        except Exception as e:
            logging.error(f"Failed to send task {task_id} result: {e}")
            if notification_claimed:
                try:
                    conn = self.db.get_connection()
                    conn.execute(
                        "UPDATE generation_tasks SET notified=0 WHERE task_id=? AND notified=-1",
                        (task_id,),
                    )
                    conn.commit()
                    conn.close()
                except Exception as reset_error:
                    logging.error(
                        f"Failed to reset notification flag for task {task_id}: {reset_error}"
                    )'''

new_except = '''        except Exception as e:
            err_str = str(e)
            # VK error 901: user blocked bot or denied permission - stop retrying
            if "901" in err_str or "Can't send messages" in err_str:
                logging.warning(
                    f"User {user_id} blocked bot or denied permission for task {task_id}, "
                    f"marking as notified to stop retry loop"
                )
                if notification_claimed:
                    try:
                        conn = self.db.get_connection()
                        conn.execute(
                            "UPDATE generation_tasks SET notified=1 WHERE task_id=?",
                            (task_id,),
                        )
                        conn.execute(
                            "UPDATE users SET is_blocked=1, block_reason=? WHERE user_id=? AND is_blocked=0",
                            ("user_denied:901", user_id),
                        )
                        conn.commit()
                        conn.close()
                    except Exception as reset_error:
                        logging.error(
                            f"Failed to mark task {task_id} as notified (901): {reset_error}"
                        )
            else:
                logging.error(f"Failed to send task {task_id} result: {e}")
                if notification_claimed:
                    try:
                        conn = self.db.get_connection()
                        conn.execute(
                            "UPDATE generation_tasks SET notified=0 WHERE task_id=? AND notified=-1",
                            (task_id,),
                        )
                        conn.commit()
                        conn.close()
                    except Exception as reset_error:
                        logging.error(
                            f"Failed to reset notification flag for task {task_id}: {reset_error}"
                        )'''

if old_except in content:
    content = content.replace(old_except, new_except)
    with open("vk_bot_lp.py", "w") as f:
        f.write(content)
    print("OK: VK 901 guard added")
else:
    print("FAIL: pattern not found")
    # debug
    idx = content.find("except Exception as e:")
    if idx >= 0:
        print(f"Found exception handler at pos {idx}")
        print(repr(content[idx:idx+700]))
