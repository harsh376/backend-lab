output "bucket_name" {
  description = "Name of the media asset bucket."
  value       = aws_s3_bucket.media_assets.id
}

output "bucket_arn" {
  description = "ARN of the media asset bucket."
  value       = aws_s3_bucket.media_assets.arn
}

output "queue_name" {
  description = "Name of the media processing queue."
  value       = aws_sqs_queue.media_processing.name
}

output "queue_url" {
  description = "URL of the media processing queue."
  value       = aws_sqs_queue.media_processing.url
}

output "queue_arn" {
  description = "ARN of the media processing queue."
  value       = aws_sqs_queue.media_processing.arn
}
