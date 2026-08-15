output "ec2_public_ip" {
  description = "Public IP address of the t3.small EC2 instance"
  value       = aws_instance.buildwise.public_ip
}

output "ec2_public_dns" {
  description = "Public DNS URL of the EC2 instance"
  value       = aws_instance.buildwise.public_dns
}

output "web_os_url" {
  description = "Public URL to access the BuildWise AI OS Console"
  value       = "http://${aws_instance.buildwise.public_ip}/"
}

output "security_credentials" {
  description = "Login credentials for HTTP Basic Authentication"
  value = {
    username = var.security_user
    password = var.security_password
  }
}
