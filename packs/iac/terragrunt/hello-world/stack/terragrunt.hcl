terraform {
  source = "./modules/hello"
}

inputs = {
  message = get_env("HELLO_MESSAGE", "hello from pack")
}
