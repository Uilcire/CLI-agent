"""Background worker: generate and save a session digest after the main process exits.

Invoked by session.py via subprocess:
    python -m agent.memory.digest_worker --session-id <id> --data-dir <path>
"""

import argparse
import sys


def run_digest(session_id: str, data_dir: str) -> None:
    """Load a persisted session and generate+save its digest. Called by main() and tests."""
    from agent.config.settings import load_settings
    from agent.logger import get_logger
    from agent.memory.digest import derive_digest, merge_learnings
    from agent.memory.llm import RealLLMClient
    from agent.memory.store import LocalMemoryStore

    log = get_logger(__name__)
    settings = load_settings()
    store = LocalMemoryStore(data_dir)
    llm = RealLLMClient(settings)

    session = store.load_active_session(session_id)
    if session is None:
        log.warning("digest_worker: session not found: %s", session_id)
        return

    digest = derive_digest(session, llm)
    store.save_digest(digest)

    if session.project_id is not None:
        project = store.get_project(session.project_id)
        if project is not None:
            merged = merge_learnings(project.learnings, digest.learnings, llm)
            project.learnings = merged
            if session.session_id not in project.sessions:
                project.sessions.append(session.session_id)
            store.save_project(project)

    try:
        from agent.memory.personality import extract_feedback, patch_soul

        prefs = extract_feedback(session, llm)
        if prefs:
            personality = store.get_personality()
            if personality is not None:
                updated = patch_soul(personality, prefs, llm)
                store.save_personality(updated)
                log.info("digest_worker: personality updated")
    except Exception as e:
        log.exception("digest_worker: personality feedback failed: %s", e)

    store.delete_active_session(session_id)
    log.info("digest_worker: digest saved for session %s", session_id)


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate session digest in background")
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--data-dir", required=True)
    args = parser.parse_args()

    try:
        run_digest(args.session_id, args.data_dir)
    except Exception as e:
        try:
            from agent.logger import get_logger
            get_logger(__name__).exception("digest_worker: fatal error: %s", e)
        except Exception:
            pass
        sys.exit(1)


if __name__ == "__main__":
    main()
