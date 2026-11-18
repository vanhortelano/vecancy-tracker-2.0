"""Tenant Information: private per admin, only the requested fields, photos protected on the server."""
from conftest import api, commit, mkuser

JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 200
INFO = {"name": "Ana Reyes", "contact": "0917 123 4567", "address": "12 Mabini St, Iloilo City",
        "ec1": {"name": "Rosa Reyes", "phone": "0918 555 0000", "relation": "Mother"},
        "ec2": {"name": "Tito Ben", "phone": "0919 111 2222", "relation": "Other", "relationOther": "Uncle"}}


def put_photo(c, tok, tid, data, ctype="image/jpeg"):
    h = {"Authorization": "Bearer " + tok, "Content-Type": ctype}
    r = c.put("/api/tenant-photo/" + tid, data=data, headers=h)
    return r.status_code, r.get_json()


def test_owner_saves_and_reads_tenant_information(env):
    c, _ = env
    a = mkuser(c, "A")
    assert commit(c, a, [{"op": "set", "path": ["users", "A", "tenants", "t1"], "data": INFO}])[0] == 200
    doc = api(c, "/api/get", a, {"path": ["users", "A", "tenants", "t1"]})[1]["data"]
    assert doc["ec2"]["relationOther"] == "Uncle" and doc["contact"] == "0917 123 4567"
    # the bed points to the record; editing the record does not create a second one
    assert commit(c, a, [{"op": "update", "path": ["users", "A", "tenants", "t1"], "data": {"contact": "0917 000 0000"}}])[0] == 200
    assert len(api(c, "/api/query", a, {"path": ["users", "A", "tenants"]})[1]["docs"]) == 1


def test_only_requested_fields_and_valid_values_are_accepted(env):
    c, _ = env
    a = mkuser(c, "A")
    bad = [dict(INFO, bloodType="O+"), dict(INFO, name=""), dict(INFO, contact="call me"),
           dict(INFO, ec1={"name": "X", "phone": "1", "relation": "Boss"}), dict(INFO, ec1={"name": "X", "age": 40})]
    for data in bad:
        assert commit(c, a, [{"op": "set", "path": ["users", "A", "tenants", "t1"], "data": data}])[0] == 403, data


def test_another_admin_cannot_see_or_change_tenant_information_or_photos(env):
    c, _ = env
    a, b = mkuser(c, "A"), mkuser(c, "B")
    commit(c, a, [{"op": "set", "path": ["users", "A", "tenants", "t1"], "data": INFO}])
    assert api(c, "/api/get", b, {"path": ["users", "A", "tenants", "t1"]})[0] == 403
    assert api(c, "/api/query", b, {"path": ["users", "A", "tenants"]})[0] == 403
    assert commit(c, b, [{"op": "update", "path": ["users", "A", "tenants", "t1"], "data": {"name": "X"}}])[0] == 403
    assert put_photo(c, a, "t1", JPEG)[0] == 200
    assert c.get("/api/tenant-photo/t1", headers={"Authorization": "Bearer " + b}).status_code == 404   # B has no such photo
    assert put_photo(c, b, "t1", JPEG)[0] == 404                                                       # B cannot write A's
    assert c.get("/api/tenant-photo/t1").status_code == 401                                            # not signed in


def test_photo_upload_is_validated_and_versioned(env):
    c, _ = env
    a = mkuser(c, "A")
    assert put_photo(c, a, "nope", JPEG)[0] == 404                       # record must exist first
    commit(c, a, [{"op": "set", "path": ["users", "A", "tenants", "t1"], "data": INFO}])
    assert put_photo(c, a, "t1", b"<svg onload=alert(1)>", "image/svg+xml")[0] == 400
    assert put_photo(c, a, "t1", b"MZ\x90\x00 not an image", "image/jpeg")[0] == 400   # wrong content for the type
    assert put_photo(c, a, "t1", b"\xff\xd8\xff" + b"0" * 1_600_000)[0] in (400, 413)  # too big
    s, d = put_photo(c, a, "t1", JPEG)
    assert s == 200 and isinstance(d["photoVersion"], int)
    assert api(c, "/api/get", a, {"path": ["users", "A", "tenants", "t1"]})[1]["data"]["photoVersion"] == d["photoVersion"]
    r = c.get("/api/tenant-photo/t1", headers={"Authorization": "Bearer " + a})
    assert r.status_code == 200 and r.data == JPEG and r.headers["Content-Type"] == "image/jpeg"
    assert "no-store" in r.headers["Cache-Control"]
    assert put_photo(c, a, "t1", b"\x89PNG\r\n\x1a\n" + b"1" * 50, "image/png")[0] == 200   # replace
    assert c.get("/api/tenant-photo/t1", headers={"Authorization": "Bearer " + a}).headers["Content-Type"] == "image/png"


def test_philippine_mobile_numbers(env):
    c, _ = env
    a = mkuser(c, "A")
    ok = ["09171234567", "0917-123-4567", "0917 123 4567", "+639171234567", "+63 917 123 4567", "+63 917-123-4567", "", None]
    bad = ["0917123456", "091712345678", "08171234567", "+63917123456", "+6309171234567", "639171234567",
           "0917abc4567", "(0917) 123 4567", "0917.123.4567", "+63+9171234567", "9171234567"]
    for n in ok:
        assert commit(c, a, [{"op": "set", "path": ["users", "A", "tenants", "t1"], "data": dict(INFO, contact=n)}])[0] == 200, n
        assert commit(c, a, [{"op": "set", "path": ["users", "A", "tenants", "t1"],
                              "data": dict(INFO, ec1={"name": "R", "phone": n, "relation": "Mother"})}])[0] == 200, n
    for n in bad:
        assert commit(c, a, [{"op": "set", "path": ["users", "A", "tenants", "t1"], "data": dict(INFO, contact=n)}])[0] == 403, n
        assert commit(c, a, [{"op": "set", "path": ["users", "A", "tenants", "t1"],
                              "data": dict(INFO, ec2={"name": "R", "phone": n, "relation": "Father"})}])[0] == 403, n
    # optional details may stay empty: only the name is needed
    assert commit(c, a, [{"op": "set", "path": ["users", "A", "tenants", "t2"], "data": {"name": "No Details Yet"}}])[0] == 200


def test_supporting_documents_upload_view_replace_remove(env):
    c, _ = env
    a, b = mkuser(c, "A"), mkuser(c, "B")
    commit(c, a, [{"op": "set", "path": ["users", "A", "tenants", "t1"], "data": INFO}])
    h = lambda tok, ctype=None, name=None: dict({"Authorization": "Bearer " + tok}, **({"Content-Type": ctype} if ctype else {}),
                                                **({"X-File-Name": name} if name else {}))
    pdf = b"%PDF-1.4\n" + b"x" * 100
    assert c.post("/api/tenant-files/t1", data=b"MZ evil", headers=h(a, "application/pdf", "x.pdf")).status_code == 400
    assert c.post("/api/tenant-files/t1", data=b"<html>", headers=h(a, "text/html", "x.html")).status_code == 400
    assert c.post("/api/tenant-files/nope", data=pdf, headers=h(a, "application/pdf", "x.pdf")).status_code == 404
    r = c.post("/api/tenant-files/t1", data=pdf, headers=h(a, "application/pdf", "Birth%20Certificate.pdf"))
    assert r.status_code == 200
    fid = r.get_json()["id"]
    files = c.get("/api/tenant-files/t1", headers=h(a)).get_json()["files"]
    assert files[0]["name"] == "Birth Certificate.pdf" and files[0]["size"] == len(pdf)
    got = c.get("/api/tenant-files/t1/" + fid, headers=h(a))
    assert got.status_code == 200 and got.data == pdf and "no-store" in got.headers["Cache-Control"]
    # another admin sees nothing and cannot change or delete it
    assert c.get("/api/tenant-files/t1", headers=h(b)).get_json()["files"] == []
    assert c.get("/api/tenant-files/t1/" + fid, headers=h(b)).status_code == 404
    assert c.delete("/api/tenant-files/t1/" + fid, headers=h(b)).status_code == 404
    png = b"\x89PNG\r\n\x1a\n" + b"y" * 40
    assert c.put("/api/tenant-files/t1/" + fid, data=png, headers=h(a, "image/png", "ID.png")).status_code == 200
    assert c.get("/api/tenant-files/t1/" + fid, headers=h(a)).data == png
    assert c.delete("/api/tenant-files/t1/" + fid, headers=h(a)).status_code == 200
    assert c.get("/api/tenant-files/t1", headers=h(a)).get_json()["files"] == []
    assert c.get("/api/tenant-files/t1").status_code == 401
