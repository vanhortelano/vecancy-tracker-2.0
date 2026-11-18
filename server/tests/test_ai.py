from conftest import api, commit, mkuser, scalar


def room(n, tenant, end):
    return {"room": n, "capacity": 2, "tenancyMode": "Bedspace", "beds": [
        {"slot": "Bed 1", "tenant": tenant, "start": "2020-01-01", "end": end}, {"slot": "Bed 2", "tenant": None}]}


def test_assistant_reads_sql_and_stores_history_and_insights(env):
    c, _ = env
    a = mkuser(c, "A")
    commit(c, a, [{"op": "set", "path": ["users", "A", "rooms", "r1"], "data": room("101", "Ann", "2099-01-01")},
                  {"op": "set", "path": ["users", "A", "rooms", "r2"], "data": room("102", "Bob", "2000-01-01")}])
    s, d = api(c, "/api/assistant", a, {"question": "how many vacant beds?"})
    assert s == 200 and d["scope"] == "tracker" and d["action"] == {"type": "none"}
    assert "2 vacant beds" in d["response"] and "Room 101 (1)" in d["response"]
    cid = d["conversationId"]
    s, d2 = api(c, "/api/assistant", a, {"question": "how do I add a room?", "conversationId": cid})
    assert d2["conversationId"] == cid
    s, h = api(c, "/api/assistant/history", a, {"conversationId": cid})
    assert [m["role"] for m in h["messages"]] == ["user", "assistant", "user", "assistant"]
    assert scalar(c, "select count(*) from ai_insights where owner_uid='A' and kind='live_vacant'") == 1


def test_assistant_only_sees_the_callers_own_data_and_history(env):
    c, _ = env
    a, b = mkuser(c, "A"), mkuser(c, "B")
    commit(c, a, [{"op": "set", "path": ["users", "A", "rooms", "r1"], "data": room("101", "Ann", "2099-01-01")}])
    cid = api(c, "/api/assistant", a, {"question": "vacant beds please"})[1]["conversationId"]
    d = api(c, "/api/assistant", b, {"question": "vacant beds please"})[1]
    assert "don't have any rooms" in d["response"]                  # B sees none of A's rooms
    d2 = api(c, "/api/assistant", b, {"question": "how do I add a room?", "conversationId": cid})[1]
    assert d2["conversationId"] != cid                              # cannot append to A's conversation
    assert api(c, "/api/assistant/history", b, {"conversationId": cid})[1]["messages"] == []
    assert api(c, "/api/assistant", None, {"question": "hi"})[0] == 401


def test_offtopic_and_validation(env):
    c, _ = env
    a = mkuser(c, "A")
    assert api(c, "/api/assistant", a, {"question": "weather today"})[1]["scope"] == "unrelated"
    assert api(c, "/api/assistant", a, {"question": "   "})[0] == 400
