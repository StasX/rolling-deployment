#!/bin/bash
set -e

cd "$(dirname "${BASH_SOURCE[0]}")"
export PATH="$HOME/.local/bin:$PATH"

if [ -f .env ]; then
  set -a
  # shellcheck source=.env
  source <(sed 's/\r$//' .env)
  set +a
fi

if [ -n "$PROJECT_NAME" ]; then
  export TF_VAR_PROJECT_NAME="$PROJECT_NAME"
fi

if [ -n "$MOST_RECENT" ]; then
  export TF_VAR_MOST_RECENT="$MOST_RECENT"
fi

if [ -n "$AMI_ID" ]; then
  export TF_VAR_AMI_ID="$AMI_ID"
fi

if [ -n "$USE_DOMAIN" ]; then
  export TF_VAR_USE_DOMAIN="$USE_DOMAIN"
fi

if [ -n "$DOMAIN_NAME" ]; then
  export TF_VAR_DOMAIN_NAME="$DOMAIN_NAME"
fi

if [ -n "$ADMIN_ALLOWED_CIDR" ]; then
  export TF_VAR_ADMIN_ALLOWED_CIDR="$ADMIN_ALLOWED_CIDR"
fi

bash ./scripts/generate_ssh_key.sh

bash ./scripts/install_python.sh

bash ./scripts/install_terraform.sh

bash ./scripts/install_ansible.sh

python3 -m venv env
env/bin/python -m pip install -r requirements.txt

env/bin/python main.py --apply "$@"
