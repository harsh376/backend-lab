variable "bucket_name" {
  description = "Globally unique name for the media asset bucket."
  type        = string
}

variable "queue_name" {
  description = "Name for the media processing queue."
  type        = string
}

variable "tags" {
  description = "Additional tags to apply to media processing resources."
  type        = map(string)
  default     = {}
}
