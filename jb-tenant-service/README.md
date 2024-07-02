# Tenant Service

Tenant Service is a collection of APIs that are specific to the **Jugalbandi Tenant application** which provides the necessary endpoints for handling tenant related data. It uses FastAPI and PostgreSQL to achieve the task at hand.

# 🔧 1. Installation

To use the code, you need to follow these steps:

1. Clone the repository from GitHub:

```bash
  git clone git@github.com:OpenNyAI/jugalbandi.git
```

2. The code requires **Python 3.11 or higher** and the project follows poetry package system. If poetry is already installed, skip this step. To install [poetry](https://python-poetry.org/docs/), run the following command in your terminal:

```bash
  curl -sSL https://install.python-poetry.org | python3 -
```

3. Once poetry is installed, go into the **jb-tenant-service** folder in the terminal and run the following commands to install the dependencies and create a virtual environment:

```bash
  poetry install
  source .venv/bin/activate
```

4. Create an environment file **.env** inside the jb-tenant-service folder which will hold the development credentials and add the following variables. Update the openai_api_key and your db connections appropriately.

   ```bash
   OPENAI_API_KEY=<your_openai_api_key>
   POSTGRES_DATABASE_NAME=<your_db_name>
   POSTGRES_DATABASE_USERNAME=<your_db_username>
   POSTGRES_DATABASE_PASSWORD=<your_db_password>
   POSTGRES_DATABASE_IP=<your_db_public_ip>
   POSTGRES_DATABASE_PORT=5432

   # Auth env variables
   TOKEN_ALGORITHM=<your_auth_token_algorithm>
   TOKEN_JWT_SECRET_KEY=<your_jwt_secret_key>
   TOKEN_JWT_SECRET_REFRESH_KEY=<your_jwt_secret_refresh_key>
   ACCESS_TOKEN_EXPIRY_MINUTES=60
   REFRESH_TOKEN_EXPIRY_DAYS=1

   # Email credentials
   EMAIL_API_KEY=<sendgrid_api_key>
   APP_BASE_URL=<frontend_base_url>
   APP_SUB_URL=<frontend_sub_url>
   ```

# 🏃🏻 2. Running

Once the above installation steps are completed, run the following command in jb-tenant-service folder of the repository in terminal:

```bash
  poetry run poe start
```

# 🚀 3. Deployment

This repository comes with a Dockerfile which is present under the tools subfolder. You can use this dockerfile to deploy your version of this application to Cloud Run in GCP.
Make the necessary changes to your dockerfile with respect to your new changes. (Note: The given Dockerfile will deploy the base code without any error, provided you added the required environment variables (mentioned in the .env file) to either the Dockerfile or the cloud run revision). You can run the following command to build the docker image:

```bash
poetry run poe build
```

# 📜🖋 4. Poetry commands

- All the poetry commands like install, run, build, test, etc. are wrapped inside a script called **poe**. You can check out and customize the commands in **pyproject.toml** file.
- Adding package through poetry:

  - To add a new python package to the project, run the following command:

    ```bash
    poetry add <package-name>
    ```

  - To add a custom package to the project, run the following command:

    ```bash
    poetry add <path_to_custom_package> --editable
    ```

- Removing package through poetry:

  - To remove a python package from the project, run the following command:

    ```bash
    poetry remove <package-name>
    ```

- Running tests through poetry:

  - To run all the tests, run the following command:

    ```bash
    poetry run poe test
    ```

  - To run a specific test, run the following command:

    ```bash
    poetry run poe test <path_to_test_file>
    ```
