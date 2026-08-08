from backend.agent.tools.memory_tools import (
    delete_core_memory,
    get_core_memories,
    memory_read_allowed,
    memory_write_allowed,
    search_core_memories,
    set_current_conversation_mode,
    set_current_user,
)


def test_isolated_mode_blocks_reads_and_writes():
    set_current_user("isolated-test-user")
    try:
        set_current_conversation_mode("isolated")

        assert memory_read_allowed() is False
        assert memory_write_allowed() is False

        read_result = get_core_memories()
        assert read_result["allowed"] is False
        assert read_result["memories"] == []

        delete_result = delete_core_memory("anything")
        assert delete_result["deleted"] is False
    finally:
        set_current_conversation_mode("normal")


def test_no_write_mode_still_allows_reads():
    set_current_user("no-write-test-user")
    try:
        set_current_conversation_mode("no_write")

        assert memory_read_allowed() is True
        assert memory_write_allowed() is False
    finally:
        set_current_conversation_mode("normal")


def test_isolated_mode_blocks_on_demand_memory_search():
    set_current_user("isolated-search-test-user")
    try:
        set_current_conversation_mode("isolated")
        result = search_core_memories("project")
        assert result["allowed"] is False
        assert result["memories"] == []
    finally:
        set_current_conversation_mode("normal")
