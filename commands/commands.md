

# Build the image
docker build -t open-webui:local .

# Remove any existing container with the same name (safe if none exists)
docker rm -f open-webui

# Run the container with your .env configuration
docker run -d -p 3000:8080 -v open-webui:/app/backend/data --env-file docker.local.env --network nova-net --name open-webui --restart unless-stopped open-webui:local

# WSL Activating command
wsl -d Ubuntu
cd ~ && cd ~/projects/open-webui/


//For running locally in wsl backend
    bash run-dev.sh


    ## Backend (WSL, native — first-time setup)
    cd ~/projects/open-webui/backend

    # Create venv pinned to Python 3.11 (only needed once)
    uv python install 3.11
    uv venv --python 3.11
    source .venv/bin/activate
    uv pip install -r requirements.txt

    cd ~/projects/open-webui/backend
    bash run-dev.sh

    ## Frontend
    cd ~/projects/open-webui
    nvm use 22          # only needed once per new shell if not set as default
    npm ci

    cd ~/projects/open-webui
    npm run dev

    # Terminal 1
    cd ~/projects/open-webui/backend && bash run-dev.sh

    # Terminal 2
    cd ~/projects/open-webui && npm run dev

//For resyncinging code into wsl
rsync -a --info=progress2 \
  --exclude='.git' \
  --exclude='node_modules' \
  --exclude='.svelte-kit' \
  --exclude='graphify-out' \
  --exclude='.venv' \
  --exclude='**/.venv' \
  --exclude='__pycache__' \
  --exclude='docker.local.env' \
  "/mnt/d/My Projects/OpenWeb Ui/open-webui/" \
  "$HOME/projects/open-webui/"
