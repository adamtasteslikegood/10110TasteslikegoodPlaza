## User

write me a cheat sheet for heredocs, pipes and stdin out redirections and cmd substituitiopnms

## Assistant

# Bash Cheat Sheet: Redirections, Pipes, Heredocs & Command Substitution

## 1. I/O Redirections

### Basic File Redirections
```bash
# Output redirection (> overwrites, >> appends)
echo "Hello" > file.txt          # Write to file (overwrite)
echo "World" >> file.txt         # Append to file
command > file.txt              # Redirect stdout to file
command 2> error.log            # Redirect stderr to file
command &> all.log              # Redirect stdout + stderr to file
command > out.log 2>&1          # Redirect both to stdout, then to file

# Input redirection
command < file.txt              # Read from file
cat file.txt | command           # Pipe input
```

### Descriptor Numbers
- `0` = stdin (keyboard)
- `1` = stdout (screen)
- `2` = stderr (screen)

### Redirecting to/from Descriptors
```bash
command 2>&1                    # stderr → stdout
command 1>&2                    # stdout → stderr
command >/dev/null 2>&1         # Discard all output (/dev/null)

# Swap stdout/stderr
command 3>&1 1>&2- 2>&3-        # Complex swapping
```

### Here Strings (Quick input)
```bash
command <<< "input string"      # Feed string to command
sort <<< "banana\napple\ncherry"
```

## 2. Pipes (`|`)

### Basic Pipes
```bash
# Chain commands: output of first becomes input of second
ls -la | grep ".txt"            # Filter files
ps aux | grep "nginx"           # Find processes
cat file.txt | sort | uniq -c   # Count unique lines

# Multiple pipes
find /var/log -name "*.log" | xargs grep "error" | sort | uniq
```

### Pipe with Process Substitution
```bash
# Feed multiple files as if they were one
diff <(sort file1.txt) <(sort file2.txt)

# Compare directories
diff -r <(ls dir1) <(ls dir2)

# Multiple inputs to command
paste <(cut -d, -f1 file1.csv) <(cut -d, -f2 file2.csv)
```

### Named Pipes (`mkfifo`)
```bash
# Create named pipe
mkfifo mypipe
# Writer in one terminal
echo "data" > mypipe
# Reader in another terminal
cat < mypipe
rm mypipe                       # Clean up
```

## 3. Heredocs (`<<`)

### Basic Heredoc
```bash
# Multi-line input to command
cat << EOF > script.sh
#!/bin/bash
echo "Hello, $USER"
for i in {1..5}; do
    echo "Count: $i"
done
EOF

# Execute immediately
cat << 'EOF'
This is literal text
No variable expansion
EOF
```

### Heredoc Variations

#### Quote-delimited (no expansion)
```bash
cat << 'EOF' > config.conf
server {
    listen 80;
    server_name example.com;
}
EOF
```

#### Variable expansion
```bash
cat << EOF > config.conf
server {
    listen $PORT;
    server_name $DOMAIN;
}
EOF

# Set variables before heredoc
PORT=8080 DOMAIN=example.com cat << EOF > config.conf
...
EOF
```

#### Trim whitespace
```bash
# Remove leading tabs (not spaces)
cat <<- EOF > script.sh
    #!/bin/bash
        echo "Indented content"
            EOF

# Remove common leading whitespace
cat << 'EOF' | sed 's/^[[:space:]]*//' > clean.sh
    Line 1
        Line 2
    Line 3
EOF
```

### Heredoc with Commands
```bash
# SQL example
mysql -u user -p database << 'SQL'
CREATE TABLE users (
    id INT PRIMARY KEY AUTO_INCREMENT,
    name VARCHAR(100),
    email VARCHAR(100) UNIQUE
);
INSERT INTO users (name, email) VALUES 
('Alice', 'alice@example.com'),
('Bob', 'bob@example.com');
SELECT * FROM users;
SQL

# SSH with heredoc
ssh user@server << 'COMMANDS'
sudo systemctl restart nginx
sudo systemctl status nginx
tail -f /var/log/nginx/error.log
# Ctrl+D to end
COMMANDS
```

### Advanced Heredoc Patterns
```bash
# Dynamic content
read -p "Enter name: " name
cat << EOF
Dear $name,

Welcome to our system.
Your account was created on $(date).

Best regards,
Support Team
EOF

# Template processing
template="Hello {name}, your balance is {amount}"
name="Alice" amount=1000 eval "echo $template"

# Or with heredoc
cat << EOF
$(printf "$template" name="$name" amount="$amount")
EOF
```

## 4. Command Substitution

### Two Forms
```bash
# $(command) - preferred, nested-friendly
result=$(date +%Y-%m-%d)
files=$(ls *.txt)

# Backticks `command` - older style, avoid nesting
result=`date +%Y-%m-%d`
files=`ls *.txt`
```

### Basic Usage
```bash
# Variable assignment
today=$(date +%Y-%m-%d_%H:%M:%S)
backup_dir="backup_$(date +%Y%m%d)"

# In commands
echo "Log file: /var/log/app_$(date +%Y%m%d).log"
cp file.txt "backup_$(date +%s).txt"

# Counting
file_count=$(ls -1 | wc -l)
line_count=$(wc -l < file.txt)

# File operations
mkdir -p "logs/$(date +%Y/%m/%d)"
mv *.log "logs/$(date +%Y%m%d)/"
```

### With Quotes & Special Characters
```bash
# Preserve spaces and newlines
content=$(cat file.txt)         # Collapses newlines to spaces
content=$(cat file.txt | tr '\n' ' ')  # Explicit space replacement

# Preserve literal newlines
content=$(cat file.txt; echo)   # Preserves newlines

# Quoted substitution
files=$(ls -1 *.txt)
for file in $files; do          # Word splitting occurs
    echo "Processing $file"
done

# Better: use array
mapfile -t files < <(ls *.txt)
for file in "${files[@]}"; do
    echo "Processing $file"
done
```

### Nested Substitution
```bash
# $(()) works better than backticks for nesting
year=$(date +%Y)
month=$(date +%m)
day=$(date +%d)
filename="report_${year}${month}${day}.csv"

# Complex nesting
output_dir="/backups/$(hostname -s)/$(date +%Y)/$(date +%m)"
mkdir -p "$output_dir"

# Multiple substitutions
echo "Server: $(hostname -s), Time: $(date +%H:%M), Users: $(who | wc -l)"
```

### Error Handling in Substitution
```bash
# Check if command succeeded
if output=$(command); then
    echo "Success: $output"
else
    echo "Command failed with exit code $?"
fi

# Default values
files=$(ls *.txt 2>/dev/null || echo "no_files.txt")
count=${files:-0}

# Timeout for long-running commands
timeout 10s command || echo "Command timed out"
```

## 5. Common Patterns & Combinations

### Log Rotation Pattern
```bash
#!/bin/bash
logdir="/var/log/app"
timestamp=$(date +%Y%m%d_%H%M%S)

# Rotate logs
for log in "$logdir"/*.log; do
    if [[ -f "$log" ]]; then
        mv "$log" "${log%.log}_${timestamp}.log"
    fi
done

# Create new log
touch "$logdir/app.log"
chmod 644 "$logdir/app.log"
```

### Backup Script
```bash
#!/bin/bash
backup_dir="/backup/$(date +%Y-%m-%d)"
mkdir -p "$backup_dir"

# Find and backup important files
find /home -name "*.conf" -o -name "*.key" | while read file; do
    if [[ -r "$file" ]]; then
        cp "$file" "$backup_dir/$(basename "$file")"
        echo "Backed up: $file"
    fi
done > "$backup_dir/backup.log" 2>&1

# Create manifest
ls -la "$backup_dir" > "$backup_dir/manifest.txt"
```

### Database Export
```bash
#!/bin/bash
db_name="myapp"
backup_dir="db_backups/$(date +%Y%m%d)"
mkdir -p "$backup_dir"

# Export with heredoc for complex queries
mysqldump -u user -p"$DB_PASS" "$db_name" << SQL > "$backup_dir/${db_name}_$(date +%Y%m%d_%H%M%S).sql"
-- Only specific tables
-- DROP TABLE IF EXISTS users, orders;
-- SET foreign_key_checks = 0;
SQL

# Compress
tar -czf "$backup_dir/${db_name}_$(date +%Y%m%d).tar.gz" -C "$backup_dir" .
```

### Process Monitoring
```bash
#!/bin/bash
# Watch processes and log to file
logfile="monitoring_$(date +%Y%m%d).log"

{
    echo "=== Process Monitor Started: $(date) ==="
    while true; do
        echo "=== $(date) ==="
        ps aux | grep "[m]yapp" | awk '{print $2, $11}' >> /tmp/pids.tmp
        cat /tmp/pids.tmp | sort -u
        sleep 60
    done
} > "$logfile" 2>&1 &

echo $! > /tmp/monitor.pid
```

### Configuration Generation
```bash
#!/bin/bash
# Generate nginx config from template
cat << EOF > /etc/nginx/sites-available/app.conf
server {
    listen $(grep PORT .env | cut -d= -f2 || echo 80);
    server_name $(hostname -f);
    
    location / {
        proxy_pass http://localhost:$(grep API_PORT .env | cut -d= -f2 || echo 3000);
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
    }
    
    access_log /var/log/nginx/app_$(date +%Y%m%d).log;
    error_log /var/log/nginx/app_error.log;
}
EOF

nginx -t && systemctl reload nginx
```

## 6. Debugging Tips

### Trace Execution
```bash
# Enable debug mode
set -x
command with substitutions
set +x

# Or for entire script
bash -x script.sh

# Trace specific command
bash -x -c 'echo $(date) | tee log.txt'
```

### Check Substitutions
```bash
# See what command substitution produces
echo "DEBUG: \$(ls): $(ls)"
echo "DEBUG: Files: [$(ls *.txt 2>/dev/null || echo 'none')]"
```

### Handle Empty Results
```bash
# Prevent errors with empty substitution
files=$(ls *.txt 2>/dev/null)
if [[ -n "$files" ]]; then
    echo "Found files: $files"
else
    echo "No .txt files found"
fi

# Or default value
file_list="${files:-'no files'}"
```

This cheat sheet covers the essential patterns you'll use 90% of the time. Start with basic redirections and pipes, then gradually incorporate heredocs for complex input and command substitution for dynamic content. The key is understanding that output from one command becomes input for the next—master that flow and everything else falls into place!

