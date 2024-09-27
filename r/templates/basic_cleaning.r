clean_rows_cols <- function(data_in){
  library(janitor)
  # Initial counts
  initial_rows <- nrow(data_in)
  initial_cols <- ncol(data_in)
  
  # Check for and remove null columns
  data_temp <- remove_empty(data_in, which = "cols", quiet = TRUE)
  removed_cols_count <- initial_cols - ncol(data_temp)
  
  # Check for and remove null rows
  data_temp <- remove_empty(data_temp, which = "rows", quiet = TRUE)
  removed_rows_count <- initial_rows - nrow(data_temp)
  
  # Check for and remove duplicates
  data_out <- distinct(data_temp)
  
  # Final counts
  final_rows <- nrow(data_out)
  final_cols <- ncol(data_out)
  
  # Print counts
  cat("Removed", removed_cols_count, "null columns.\n")
  cat("Removed", removed_rows_count, "null rows.\n")
  cat("Removed", initial_rows - final_rows, "duplicate rows.\n")
  
  return(data_out)

}
