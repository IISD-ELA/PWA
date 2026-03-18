## Quickstart: AWS CLI & RDP Instructions
    
1- Start WSL terminal
2- Connect to the AWS IAM SSO using the following command & follow the instructions provided (use 1st link, not 2nd): 

`aws sso login --sso-session iisd`
        
3- Start the EC2 instance using:

`aws --profile iisd --region ca-central-1 ec2 start-instances --instance-ids {instance id}`
        
4- Connect to EC2 session using:
        
`bash "infra/start-windows-port-forwarding.sh"`        
    
5- Once the tunnel is opened you can connect with RDP client to "localhost:3391", using the Administrator account, the password is stored in SSM under the key "/iisd-ela/config/windows/administrator-password" (Save password to keepass)
    
        
6- At the end, close the session using:

`aws --profile iisd --region ca-central-1 ec2 stop-instances --instance-ids {instance id}`

## S3 Storage

s3://iisd-ela-pwa-temp-storage/

Can be accessed via browser GUI or using an AWS CLI command like:
aws s3 sync "cypress/" "s3://iisd-ela-pwa-temp-storage/inputs/" (Access Key issue)

Can be loaded from S3 with
Aws s3 sync s3://iisd-ela-pwa-temp-storage/ Users/Administrator/code/PWA

**Within the EC2 session:**
For data, view and connect to S3 buckets using : aws s3 ls
Connect to github for code downloads (using git commands)
Run the Linux system like any other system


## Cloning repo to EC2
Repos are located under /home/ssm-user
Make sure to set up an ssh key and share add the .pub key to the github repo's access keys
Run git clone using the ssh link

[How to Git Clone with SSH: A Quick Guide](https://gitscripts.com/how-to-git-clone-with-ssh)
