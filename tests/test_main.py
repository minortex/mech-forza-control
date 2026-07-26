from src import __main__ as cli


def test_console_entrypoint_reports_errors_without_traceback(monkeypatch, capsys):
    def fail():
        raise ValueError("fan set expects -t, -i/-l, and/or one/two percentages")

    monkeypatch.setattr(cli, "_run", fail)

    assert cli.main() == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == (
        "error: fan set expects -t, -i/-l, and/or one/two percentages\n"
    )
    assert "Traceback" not in captured.err
