"""No corporate data or network calls in these regression tests."""
import asyncio
import importlib.util
from pathlib import Path
import pytest

spec=importlib.util.spec_from_file_location(
    "group_selector", Path(__file__).resolve().parents[1] / "select_pilot_group_v69.py")
selector=importlib.util.module_from_spec(spec)
spec.loader.exec_module(selector)


def test_parse_ids_rejects_bad_input():
    for value in ("", "734,,446", "734,734", "0", "-1", "abc", "  "):
        with pytest.raises(selector.SelectionError):
            selector.parse_ids(value, label="Test", max_count=10)
    assert selector.parse_ids("446, 734", label="Test", max_count=10) == [446, 734]


def test_extracts_official_shape_and_flat_list():
    data={"result":[{"USER_ID":"11","ROLE":"K"},{"USER_ID":12,"ROLE":"A"}]}
    assert selector.extract_members(data) == {11,12}
    assert selector.extract_members(data["result"]) == {11,12}


def test_rejects_ambiguous_shapes():
    for payload in ({}, {"result":{"USER_ID":"11"}}, {"error":"private"},
                    [{"bad": "secret"}], "secret"):
        with pytest.raises(selector.SelectionError):
            selector.extract_members(payload)


def test_only_approved_candidate_groups_and_counted_overlap():
    class Fake:
        def __init__(self): self.calls=[]
        async def call(self, method, params, raw=False):
            assert method=="sonet_group.user.get"
            assert raw is True
            self.calls.append(params["ID"])
            if params["ID"] == 734:
                return {"result":[{"USER_ID":1,"ROLE":"K"}]}
            return {"result":[{"USER_ID":22,"ROLE":"A"},{"USER_ID":11,"ROLE":"K"}]}

    fake=Fake()
    result=asyncio.run(selector.check_groups(fake, [734,671],[11,22]))
    assert fake.calls==[734,671]
    assert result[0]["controller_matches"] == 0
    assert not result[0]["eligible_for_next_check"]
    assert result[1]["controller_matches"] == 2
    assert result[1]["eligible_for_next_check"]
    assert all("USER_ID" not in str(item) for item in result)


def test_failure_does_not_turn_into_no_controller_result():
    class Fake:
        def call(self,*args,**kwargs):
            raise RuntimeError("secret-server-token")
    result=asyncio.run(selector.check_groups(Fake(),[671],[11]))
    assert result == [{
        "group_id":671,"status":"unavailable","members_count":None,
        "controller_matches":None,"eligible_for_next_check":False,
    }]
    assert "secret-server-token" not in str(result)
