# tuda_workspace_scripts
An overlay for the [workspace_scripts](https://github.com/tu-darmstadt-ros-pkg/workspace_scripts).

### Commands:
#### checkout [PKG]
For a given ROS pkg that is installed as a binary, add the source repo to the workspace using wstool.  

This requires the debian package versions homepage to be set to the url of the git repo followed by the branch after a '#' as separator.  
E.g.:
```
https://github.com/orga/repo.git#master
or
git@github.com:orga/repo.git#master
```


#### desourcify
Scans the workspace for repos that do not differ from the remote in any way and where all packages in the repo can be replaced with debian packages on the same branch and commit.  
The user can choose to remove parts or all of the applicable repositories and replace the packages by binaries.

This requires the debian packages to have the homepage field set to the git repository url followed by the branch as described above in `checkout`
