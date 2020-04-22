workflow "Build and Test" {
  on = "push"
  resolves = [
    "Master",
  ]
}

action "Build" {
  uses = "CrazyLionHeart/zabbix2kafka@master"
  args = "pip install -r requirements.txt"
}

action "Lint" {
  uses = "CrazyLionHeart/zabbix2kafka@master"
  args = "black --check test_python.py"
  needs = ["Build"]
}

action "Test" {
  uses = "CrazyLionHeart/zabbix2kafka@master"
  args = "pytest"
  needs = ["Build"]
}

action "Master" {
  uses = "actions/bin/filter@master"
  needs = [
    "Lint",
    "Test",
  ]
  args = "branch master"
}
