#!/usr/bin/env python3

import sqlite3
import os
import glob
import re
import shutil
import logging
import json
import tarfile
import tempfile
import argparse
import urllib.parse
import urllib
import time
import collections

import requests
from bs4 import BeautifulSoup as bs, Tag # pip install bs4
from selenium import webdriver
from selenium.webdriver.common.keys import Keys  
from selenium.webdriver.chrome.options import Options


class PoshWebDriver:
    """ Thin wrapper for selenium webdriver for page content retrieval """

    def __init__(self, executable_path = None):

        self.driver_exe_path = executable_path
        self.driver = webdriver.PhantomJS(executable_path = self.driver_exe_path)

    def get_url_page(self, url):
        """ retrieve the full html content of a page after Javascript execution """
        
        index_html = None
        try:
            self.driver.get(url)
            index_html = self.driver.page_source
        except (ConnectionResetError, urllib.error.URLError) as e:
            # we may have a triggered a anti-scraping time ban
            # Lay low for several seconds and get back to it.

            self.driver.quit()
            self.driver = webdriver.PhantomJS(executable_path = self.driver_exe_path)
            time.sleep(2)
            index_html = None

        # try a second time, and raise error if fail
        if not index_html:
            self.driver.get(url)
            index_html = self.driver.page_source

        return index_html

    def quit():
        return self.driver.quit()


class Configuration:

    # STATIC CONSTANTS
    posh_doc_api_version = '0.2' # powershell doc api version, not this docset one.
    posh_version = '6'
    docset_name = 'Powershell'

    domain = "docs.microsoft.com"
    base_url = "%s/en-us/powershell/module" % domain
    default_url = "https://%s/?view=powershell-%%s" % (base_url)
    default_theme_uri = "_themes/docs.theme/master/en-us/_themes"
    # default_toc = "https://docs.microsoft.com/api/apibrowser/powershell/modules?moniker=powershell-%s&api-version=%s"
    default_toc = "https://%s/powershell-%%s/toc.json" % (base_url)

    path_to_phantomjs = "C:\\Users\\lucas\\AppData\\Roaming\\npm\\node_modules\\phantomjs-prebuilt\\lib\\phantom\\bin\phantomjs.exe"

    def __init__(self, args):

        
        # selected powershell api version
        self.powershell_version = args.version

        # The modules and cmdlets pages are "versionned" using additional params in the GET request
        self.powershell_version_param = "view=powershell-{0:s}".format(self.powershell_version)

        # build folder (must be cleaned afterwards)
        self.build_folder = os.path.join(args.output, "_build")

        # output folder
        self.output_folder = args.output

        # powershell docs start page
        self.docs_index_url = Configuration.default_url % self.powershell_version

        # powershell docs table of contents url
        self.docs_toc_url =  "https://{0:s}/powershell-{1:s}/toc.json?{2:s}".format(
            Configuration.base_url, 
            self.powershell_version,
            self.powershell_version_param
        )

        # selenium webdriver
        self.webdriver = PoshWebDriver(Configuration.path_to_phantomjs)



def download_binary(url, output_filename):
    """ Download GET request as binary file """
    logging.debug("download_binary : %s -> %s" % (url, output_filename))

    # ensure the folder path actually exist
    os.makedirs(os.path.dirname(output_filename), exist_ok = True)

    r = requests.get(url, stream=True)
    with open(output_filename, 'wb') as f:
        for data in r.iter_content(32*1024):
            f.write(data)

def download_textfile(url : str ,  output_filename : str, params : dict = None):
    """ Download GET request as utf-8 text file """

    logging.debug("download_textfile : %s -> %s" % (url, output_filename))

    # ensure the folder path actually exist
    os.makedirs(os.path.dirname(output_filename), exist_ok = True)
    
    r = requests.get(url, data = params)
    with open(output_filename, 'w', encoding="utf8") as f:
        f.write(r.text)
    

def download_as_browser(url, output_filename):
    global global_driver
    #driver = webdriver.PhantomJS(executable_path="C:\\Users\\lucas\\AppData\\Roaming\\npm\\node_modules\\phantomjs-prebuilt\\lib\\phantom\\bin\phantomjs.exe")
    global_driver.get(url)

    #soupFromJokesCC = BeautifulSoup(driver.page_source) #page_source fetches page after rendering is complete
    with open(output_filename, 'w', encoding="utf8") as f:
        f.write(global_driver.page_source)

    #global_driver.save_screenshot(output_filename+'screen.png') # save a screenshot to disk
    


def download_and_fix_links(url, output_filepath, posh_version = Configuration.posh_version, is_index =  False, documents_folder = None):
    """ Download and fix broken nav paths for modules index """
    global global_driver
    # r = requests.get(url)
    # index_html = r.text
    #driver = webdriver.PhantomJS(executable_path="C:\\Users\\lucas\\AppData\\Roaming\\npm\\node_modules\\phantomjs-prebuilt\\lib\\phantom\\bin\phantomjs.exe")
    try:
        global_driver.get(url)
        index_html = global_driver.page_source
    except (ConnectionResetError, urllib.error.URLError) as e:
        # we may have a triggered a anti-scraping time ban
        # Lay low for several seconds and get back to it.

        global_driver.quit()
        global_driver = webdriver.PhantomJS(executable_path="C:\\Users\\lucas\\AppData\\Roaming\\npm\\node_modules\\phantomjs-prebuilt\\lib\\phantom\\bin\phantomjs.exe")
        time.sleep(2)
        index_html = None

    # try a second time, and raise error if fail
    if not index_html:
        global_driver.get(url)
        index_html = global_driver.page_source


    soup = bs(index_html, 'html.parser')

    
    links = soup.findAll("a", { "data-linktype" : "relative-path"}) # for modules and cmdlet pages
    if is_index: # for index page
        content_table = soup.findAll("table", { "class" : "api-search-results standalone"})[0]
        links = content_table.findAll(lambda tag: tag.name == 'a' and 'ms.title' in tag.attrs)    # for index page   
                
    for link in links:
        # search replace <a href="(\w+-\w+)\?view=powershell-6" data-linktype="relative-path">
        #                <a href="$1.html" data-linktype="relative-path">
        if is_index:
            link_str_pattern = "([\w\.\/]+)\?view=powershell-"
        else:
            link_str_pattern = "(\w+-\w+)\?view=powershell-"

        link_pattern = re.compile(link_str_pattern)
        targets = link_pattern.findall(link['href'])
        if not len(targets): # badly formated 'a' link
            continue

        if is_index:
            uri_path = targets[0].lstrip('/').rstrip('/')
            fixed_link = soup.new_tag("a", href="%s/index.html" % (uri_path), **{ "ms.title" : link["ms.title"]})
        else:
            fixed_link = soup.new_tag("a", href="%s.html" % targets[0], **{ "data-linktype" : "relative-path"})

        print(link['href'], " -> ", fixed_link['href']) 
        fixed_link.string = link.string
        link.replaceWith(fixed_link)

    # remove unsupported nav elements
    nav_elements = [
        ["nav", { "class" : "doc-outline", "role" : "navigation"}],
        ["ul", { "class" : "breadcrumbs", "role" : "navigation"}],
        ["div", { "class" : "sidebar", "role" : "navigation"}],
        ["div", { "class" : "dropdown dropdown-full mobilenavi"}],
        ["p", { "class" : "api-browser-description"}],
        ["div", { "class" : "api-browser-search-field-container"}],
        ["div", { "class" : "pageActions"}],
        ["div", { "class" : "dropdown-container"}],
    ]

    for nav in nav_elements:
        nav_class, nav_attr = nav
        
        for nav_tag in soup.findAll(nav_class, nav_attr):
            _ = nav_tag.extract()

    # Fix themes uri paths
    soup = crawl_posh_themes(documents_folder, soup, output_filepath)

    # Export fixed html
    with open(output_filepath, 'wb') as o_index:

        fixed_html = soup.prettify("utf-8")
        o_index.write(fixed_html)

    #global_driver.save_screenshot(output_filepath+'screen.png') # save a screenshot to disk
    return index_html

        
def crawl_posh_themes(documents_folder, soup, current_filepath):
    
    theme_output_dir = os.path.join(documents_folder, domain)

    # downloading stylesheets
    for link in soup.findAll("link", { "rel" : "stylesheet"}):
        uri_path = link['href'].strip()

        if uri_path.lstrip('/').startswith(default_theme_uri):

            css_url = "https://%s/%s" % (domain, uri_path)
            css_filepath =  os.path.join(theme_output_dir, uri_path.lstrip('/'))

            os.makedirs(os.path.dirname(css_filepath), exist_ok = True)
            
            # do not download twice the same file
            if not os.path.exists(css_filepath):
                download_textfile(css_url, css_filepath)

                # fix source map css
                # $hex_encoded_id.$name.css -> $name.css
                css_filename = os.path.basename(uri_path)
                css_dirname  = os.path.dirname(css_filepath)

                r = re.compile("\w+\.([\w\.]+)")
                sourcemap_css_filename = r.match(css_filename).groups()[0]
                download_textfile(css_url, os.path.join(css_dirname, sourcemap_css_filename))

            # Converting to a relative link
            path = os.path.relpath(css_filepath, os.path.dirname(current_filepath))
            rel_uri = '/'.join(path.split(os.sep))
            link['href'] = rel_uri

    # downloading scripts
    for script in soup.findAll("script", {"src":True}):
        uri_path = script['src']

        if  uri_path.lstrip('/').startswith(default_theme_uri):

            script_url = "https://%s/%s" % (domain, uri_path)
            
            # path normalization : we can do better
            script_path = uri_path.lstrip('/')
            if -1 != script_path.find('?v='):
                script_path = script_path[0:script_path.find('?v=')]

            script_filepath =  os.path.join(theme_output_dir, script_path)
            os.makedirs(os.path.dirname(script_filepath), exist_ok = True)

            # do not download twice the same file
            if not os.path.exists(script_filepath):
                download_textfile(script_url, script_filepath)

            # Converting to a relative link
            path = os.path.relpath(script_filepath, current_filepath)
            rel_uri = '/'.join(path.split(os.sep))
            script['src'] = rel_uri
    
    return soup


def crawl_posh_documentation(documents_folder, powershell_version = Configuration.posh_version):
    """ Crawl and download Posh modules documentation """

    index = default_url % powershell_version
    modules_toc = default_toc % (powershell_version, powershell_version)

    index_filepath = os.path.join(documents_folder, domain, "en-us", "index.html")
    download_and_fix_links(index, index_filepath, is_index= True, posh_version = powershell_version, documents_folder = documents_folder)        

    modules_filepath = os.path.join(documents_folder, "modules.toc")
    download_textfile(modules_toc, modules_filepath)

    theme_output_dir = os.path.join(documents_folder, domain, default_theme_uri)
    os.makedirs(theme_output_dir, exist_ok = True)

    with open(modules_filepath, 'r') as modules_fd:
        modules = json.load(modules_fd)

        for module in modules['items'][0]['children']:

            module_url = urllib.parse.urljoin(modules_toc, module["href"])
            module_url = "%s/?view=powershell-%s" % (module_url, powershell_version)

            module_dir = os.path.join(documents_folder, base_url, module['toc_title'])
            module_filepath = os.path.join(module_dir, "index.html")
            os.makedirs(module_dir, exist_ok = True)

            logging.debug("downloading modules doc %s -> %s" %(module_url, module_filepath))
            mod_html = download_and_fix_links(module_url, module_filepath, posh_version = powershell_version, documents_folder = documents_folder)
            

            for cmdlet in module['children']:
                cmdlet_name = cmdlet['toc_title']
                
                if cmdlet_name.lower() in ("about", "functions", "providers", "provider"): # skip special toc
                    continue
                
                logging.debug("cmdlet %s" % cmdlet)
                
                cmdlet_urlpath = cmdlet["href"]
                cmdlet_url = urllib.parse.urljoin(modules_toc, cmdlet_urlpath)
                cmdlet_url = "%s?view=powershell-%s" % (cmdlet_url, powershell_version)

                cmdlet_filepath = os.path.join(module_dir, "%s.html" % cmdlet_name)

                logging.debug("downloading cmdlet doc %s -> %s" %(cmdlet_url, cmdlet_filepath))
                cmdlet_html = download_and_fix_links(cmdlet_url, cmdlet_filepath, posh_version = powershell_version, documents_folder = documents_folder)
                

def insert_into_sqlite_db(cursor, name, record_type, path):
    """ Insert a new unique record in the sqlite database. """
    try:
        cursor.execute('SELECT rowid FROM searchIndex WHERE path = ?', (path,))
        dbpath = cursor.fetchone()
        cursor.execute('SELECT rowid FROM searchIndex WHERE name = ?', (name,))
        dbname = cursor.fetchone()

        if dbpath is None and dbname is None:
            cursor.execute('INSERT OR IGNORE INTO searchIndex(name, type, path) VALUES (?,?,?)', (name, record_type, path))
            logging.debug('DB add [%s] >> name: %s, path: %s' % (record_type, name, path))
        else:
            logging.debug('record exists')

    except:
        pass


def make_docset(source_dir, dst_dir, filename):
    """ 
    Tar-gz the build directory while conserving the relative folder tree paths. 
    Copied from : https://stackoverflow.com/a/17081026/1741450 
    """
    
    tar_filepath = os.path.join(dst_dir, '%s.tar' % filename)
    targz_filepath = os.path.join(dst_dir, '%s.tar.gz' % filename)
    docset_filepath = os.path.join(dst_dir, '%s.docset' % filename)

    with tarfile.open(tar_filepath, "w:gz") as tar:
        tar.add(source_dir, arcname=os.path.basename(source_dir))

    shutil.move(tar_filepath, targz_filepath)
    shutil.move(targz_filepath, docset_filepath) # can conflict with build dir name


def download_page_contents(configuration, uri, output_filepath):
    """ Download a page using it's uri from the TOC """

    # Resolving "absolute" url et use appropriate version
    full_url = urllib.parse.urljoin(configuration.docs_toc_url, uri)
    versionned_url = "{0:s}?{1:s}".format(full_url, configuration.powershell_version_param) 

    download_textfile(versionned_url, output_filepath)
    

def download_module_contents(configuration, module_name, module_uri, module_dir, cmdlets, root_dir):
    """ Download a modules contents """
    
    module_filepath = os.path.join(module_dir, "%s.html" % module_name)

    logging.debug("downloading %s module index page  -> %s" % (module_name, module_filepath))
    download_page_contents(configuration, module_uri, module_filepath)

    cmdlets_infos = []

    # Downloading cmdlet contents
    for cmdlet in cmdlets:

        cmdlet_name = cmdlet['toc_title']
        if cmdlet_name.lower() in ("about", "functions", "providers", "provider"): # skip special toc
            continue

        cmdlet_uri = cmdlet["href"]
        cmdlet_filepath = os.path.join(module_dir, "%s.html" % cmdlet_name)

        logging.debug("downloading %s cmdlet doc -> %s" % (cmdlet_name, cmdlet_filepath))
        download_page_contents(configuration, cmdlet_uri, cmdlet_filepath)

        cmdlets_infos.append({
            'name' : cmdlet_name,
            'path' : os.path.relpath(cmdlet_filepath, root_dir),
        })

    module_infos = {
        'name' : module_name,
        'index' : os.path.relpath(module_filepath, root_dir),
        'cmdlets' : cmdlets_infos
    }

    return module_infos

def crawl_posh_contents(configuration : Configuration, download_dir : str):
    """ Download Powershell modules and cmdlets content pages based on TOC """

    # Download toc
    logging.debug("Downloading powershell toc : %s" % (configuration.docs_toc_url))
    r = requests.get(configuration.docs_toc_url)
    modules_toc = json.loads(r.text)

    # modules_toc is a web based TOC, where as content_toc is file based
    content_toc = {}

    # Downloading modules contents
    for module in modules_toc['items'][0]['children']:

        module_name = module['toc_title']
        module_uri = module["href"]
        module_cmdlets = module['children']
        module_dir = os.path.join(download_dir, Configuration.base_url, module_name)

        module_infos = download_module_contents(configuration, module_name, module_uri, module_dir,  module_cmdlets, download_dir)
        content_toc[module_name] = module_infos

    return content_toc

def rewrite_soup(configuration : Configuration, soup, html_path : str, documents_dir : str):
    """ rewrite html contents by fixing links and remove unnecessary cruft """

    # Fix navigations links
    links = soup.findAll("a", { "data-linktype" : "relative-path"}) # for modules and cmdlet pages
    link_pattern = re.compile(r"(\w+-\w+)\?view=powershell-")

    for link in links:

        href = link['href']
        fixed_href = href

        # go back to module
        if href == "./?view=powershell-%s" % configuration.powershell_version:
            fixed_href = "./%s.html" % link.text

        # go to a cmdlet page
        else:
            targets = link_pattern.findall(href)
            if not len(targets): # badly formated 'a' link
                continue

            module_name = targets[0]
            fixed_href = "%s.html" % module_name
        
        if fixed_href != href:
            logging.debug("link rewrite : %s -> %s " % ( href, fixed_href))
            link['href'] = fixed_href

    # remove unsupported nav elements
    nav_elements = [
        ["nav"  , { "class" : "doc-outline", "role" : "navigation"}],
        ["ul"   , { "class" : "breadcrumbs", "role" : "navigation"}],
        ["div"  , { "class" : "sidebar", "role" : "navigation"}],
        ["div"  , { "class" : "dropdown dropdown-full mobilenavi"}],
        ["p"    , { "class" : "api-browser-description"}],
        ["div"  , { "class" : "api-browser-search-field-container"}],
        ["div"  , { "class" : "pageActions"}],
        ["div"  , { "class" : "container footerContainer"}],
        ["div"  , { "class" : "dropdown-container"}],
    ]

    for nav in nav_elements:
        nav_class, nav_attr = nav
        
        for nav_tag in soup.findAll(nav_class, nav_attr):
            _ = nav_tag.extract()

    # remove script elems
    for head_script in soup.head.findAll("script"):
            _ = head_script.extract()
    
    # Extract and rewrite additionnal stylesheets to download
    ThemeResourceRecord = collections.namedtuple('ThemeResourceRecord', 'url, path')

    theme_output_dir = os.path.join(documents_dir, Configuration.domain)
    theme_resources = []

    for link in soup.head.findAll("link", { "rel" : "stylesheet"}):
        uri_path = link['href'].strip()

        if not uri_path.lstrip('/').startswith(Configuration.default_theme_uri):
            continue

        # Construct (url, path) tuple
        css_url = "https://%s/%s" % (Configuration.domain, uri_path)
        css_filepath =  os.path.join(theme_output_dir, uri_path.lstrip('/'))

        # Converting href to a relative link
        path = os.path.relpath(css_filepath, os.path.dirname(html_path))
        rel_uri = '/'.join(path.split(os.sep))
        link['href'] = rel_uri

        theme_resources.append( ThemeResourceRecord( 
            url = css_url, 
            path = os.path.relpath(css_filepath, documents_dir), # stored as relative path
        ))

    return soup, set(theme_resources)

def rewrite_index_soup(configuration : Configuration, soup, index_html_path : str, documents_dir : str):
    """ rewrite html contents by fixing links and remove unnecessary cruft """

    # Fix navigations links
    content_table = soup.findAll("table", { "class" : "api-search-results standalone"})[0]
    links = content_table.findAll(lambda tag: tag.name == 'a' and 'ms.title' in tag.attrs)
    link_pattern = re.compile(r"([\w\.\/]+)\?view=powershell-")

    for link in links:

        href = link['href']
        fixed_href = href


        targets = link_pattern.findall(href)
        if not len(targets): # badly formated 'a' link
            continue

        url_path = targets[0].lstrip('/').rstrip('/')
        module_name = link.attrs['ms.title']

        fixed_href = "%s/%s.html" % (url_path, module_name)
        
        if fixed_href != href:
            logging.debug("link rewrite : %s -> %s " % ( href, fixed_href))
            link['href'] = fixed_href

    # Fix link to module.svg
    module_svg_path = os.path.join(documents_dir, Configuration.domain, "en-us", "media", "toolbars", "module.svg")
    images = content_table.findAll("img" , {'alt' : "Module"})
    for image in images:
        image['src'] =  os.path.relpath(module_svg_path, os.path.dirname(index_html_path))

    # remove unsupported nav elements
    nav_elements = [
        ["nav"  , { "class" : "doc-outline", "role" : "navigation"}],
        ["ul"   , { "class" : "breadcrumbs", "role" : "navigation"}],
        ["div"  , { "class" : "sidebar", "role" : "navigation"}],
        ["div"  , { "class" : "dropdown dropdown-full mobilenavi"}],
        ["p"    , { "class" : "api-browser-description"}],
        ["div"  , { "class" : "api-browser-search-field-container"}],
        ["div"  , { "class" : "pageActions"}],
        ["div"  , { "class" : "dropdown-container"}],
        ["div"  , { "class" : "container footerContainer"}],
        ["div"  , { "data-bi-name" : "header", "id" : "headerAreaHolder"}],
    ]

    for nav in nav_elements:
        nav_class, nav_attr = nav
        
        for nav_tag in soup.findAll(nav_class, nav_attr):
            _ = nav_tag.extract()

    # remove script elems
    for head_script in soup.head.findAll("script"):
            _ = head_script.extract()

    # Fixing and downloading css stylesheets
    theme_output_dir = os.path.join(documents_dir, Configuration.domain)
    for link in soup.head.findAll("link", { "rel" : "stylesheet"}):
        uri_path = link['href'].strip()

        if not uri_path.lstrip('/').startswith(Configuration.default_theme_uri):
            continue

        # Construct (url, path) tuple
        css_url = "https://%s/%s" % (Configuration.domain, uri_path)
        css_filepath =  os.path.join(theme_output_dir, uri_path.lstrip('/'))

        # Converting href to a relative link
        path = os.path.relpath(css_filepath, os.path.dirname(index_html_path))
        rel_uri = '/'.join(path.split(os.sep))
        link['href'] = rel_uri

        download_textfile(css_url, css_filepath)

    return soup


def rewrite_html_contents(configuration : Configuration, html_root_dir : str):
    """ rewrite every html file downloaded """

    additional_resources = set()

    for html_file in glob.glob("%s/**/*.html" % html_root_dir, recursive = True):

        logging.debug("rewrite  html_file : %s" % (html_file))

        # Read content and parse html
        with open(html_file, 'r', encoding='utf8') as i_fd:
            html_content = i_fd.read()

        soup = bs(html_content, 'html.parser')
        
        # rewrite html
        soup, resources = rewrite_soup(configuration, soup, html_file, html_root_dir)
        additional_resources = additional_resources.union(resources)

        # Export fixed html
        fixed_html = soup.prettify("utf-8")
        with open(html_file, 'wb') as o_fd:
            o_fd.write(fixed_html)

    return additional_resources


def download_additional_resources(configuration : Configuration, documents_dir : str, resources_to_dl : set = set()):
    """ Download optional resources for "beautification """

    for resource in resources_to_dl:
        
        download_textfile(
            resource.url, 
            os.path.join(documents_dir, resource.path)
        )

    # Download index start page
    index_url = Configuration.default_url % configuration.powershell_version
    index_filepath = os.path.join(documents_dir, Configuration.domain, "en-us", "index.html")

    soup = bs( configuration.webdriver.get_url_page(index_url), 'html.parser')
    soup = rewrite_index_soup(configuration, soup, index_filepath, documents_dir)
    fixed_html = soup.prettify("utf-8")
    with open(index_filepath, 'wb') as o_fd:
            o_fd.write(fixed_html)


    # Download module.svg icon for start page
    icon_module_url  =     '/'.join(["https:/"   , Configuration.domain, "en-us", "media", "toolbars", "module.svg"])
    icon_module_path = os.path.join(documents_dir, Configuration.domain, "en-us", "media", "toolbars", "module.svg")
    download_binary(icon_module_url, icon_module_path)


def create_sqlite_database(configuration, content_toc, resources_dir, documents_dir):
    """ Indexing the html document in a format Dash can understand """

    def insert_into_sqlite_db(cursor, name, record_type, path):
        """ Insert a new unique record in the sqlite database. """
        try:
            cursor.execute('SELECT rowid FROM searchIndex WHERE path = ?', (path,))
            dbpath = cursor.fetchone()
            cursor.execute('SELECT rowid FROM searchIndex WHERE name = ?', (name,))
            dbname = cursor.fetchone()

            if dbpath is None and dbname is None:
                cursor.execute('INSERT OR IGNORE INTO searchIndex(name, type, path) VALUES (?,?,?)', (name, record_type, path))
                logging.debug('DB add [%s] >> name: %s, path: %s' % (record_type, name, path))
            else:
                logging.debug('record exists')

        except:
            pass

    sqlite_filepath = os.path.join(resources_dir, "docSet.dsidx")
    if os.path.exists(sqlite_filepath):
        os.remove(sqlite_filepath)

    db = sqlite3.connect(sqlite_filepath)
    cur = db.cursor()
    cur.execute('CREATE TABLE searchIndex(id INTEGER PRIMARY KEY, name TEXT, type TEXT, path TEXT);')
    cur.execute('CREATE UNIQUE INDEX anchor ON searchIndex (name, type, path);')

    
    for module_name, module in content_toc.items():

        insert_into_sqlite_db(cur, module_name, "Module", module['index'])

        for cmdlet in module['cmdlets']:
            
            cmdlet_name = cmdlet['name']
            if cmdlet_name == module_name:
                continue

            insert_into_sqlite_db(cur, cmdlet_name, "Cmdlet", cmdlet['path'])
        

    # commit and close db
    db.commit()
    db.close()

def copy_folder(src_folder : str, dst_folder : str):
    """ Copy a full folder tree anew every time """

    def onerror(func, path, exc_info):
        """
        Error handler for ``shutil.rmtree``.

        If the error is due to an access error (read only file)
        it attempts to add write permission and then retries.

        If the error is for another reason it re-raises the error.

        Usage : ``shutil.rmtree(path, onerror=onerror)``
        """
        import stat

        if not os.path.exists(path):
            return

        if not os.access(path, os.W_OK):
            # Is the error an access error ?
            os.chmod(path, stat.S_IWUSR)
            func(path)
        else:
            raise

    shutil.rmtree(dst_folder,ignore_errors=False,onerror=onerror) 
    shutil.copytree(src_folder, dst_folder)

def main(configuration : Configuration):

    # """ Scheme for content toc : 
    # {
    #     module_name : {
    #         'name' : str,
    #         'index' : relative path,
    #         'cmdlets' : [
    #             {
    #                 'name' : str,
    #                 'path' : relative path, 
    #             },
    #             ...
    #         ]
    #     },
    #     ...
    # }
    # """
    content_toc = {}
    resources_to_dl = set()

    """ 0. Prepare folders """
    download_dir = os.path.join(configuration.build_folder, "_1_downloaded_contents")
    html_rewrite_dir = os.path.join(configuration.build_folder, "_2_html_rewrite")
    additional_resources_dir = os.path.join(configuration.build_folder, "_3_additional_resources")
    package_dir = os.path.join(configuration.build_folder, "_4_ready_to_be_packaged")

    # _4_ready_to_be_packaged is the final build dir
    docset_dir = os.path.join(package_dir, "%s.docset" % Configuration.docset_name)
    content_dir = os.path.join(docset_dir , "Contents")
    resources_dir = os.path.join(content_dir, "Resources")
    document_dir = os.path.join(resources_dir, "Documents")

    """ 1. Download html pages """
    content_toc = crawl_posh_contents(configuration, download_dir)


    """ 2.  Parse and rewrite html contents """
    copy_folder(download_dir, html_rewrite_dir)
    resources_to_dl = rewrite_html_contents(configuration, html_rewrite_dir)

    """ 3.  Download additionnal resources """
    copy_folder(html_rewrite_dir, additional_resources_dir )
    download_additional_resources(configuration, additional_resources_dir, resources_to_dl)

    """ 4.  Database indexing """
    copy_folder(additional_resources_dir, document_dir )
    create_sqlite_database(configuration, content_toc, resources_dir, document_dir)

    """ 5.  Archive packaging """
    shutil.copy("static/Info.plist", content_dir)
    shutil.copy("static/DASH_LICENSE", os.path.join(resources_dir, "LICENSE"))
    shutil.copy("static/icon.PNG", docset_dir)
    shutil.copy("static/icon@2x.PNG", docset_dir)

    version_output_dir = os.path.join(configuration.output_folder, "versions", "%s" % configuration.powershell_version)
    os.makedirs(version_output_dir, exist_ok=True)

    make_docset(
        docset_dir,
        version_output_dir,
        Configuration.docset_name
    )


def old_main(configuration : Configuration):

    # Docset archive format
    """ 
        $root/
            $docset_name.docset/
                Contents/
                    Info.plist
                    Resources/
                        LICENSE
                        docSet.dsidx
                        Documents/
                            *
    """
    docset_dir = os.path.join(build_dir, "%s.docset" % docset_name)
    content_dir = os.path.join(docset_dir , "Contents")
    resources_dir = os.path.join(content_dir, "Resources")
    document_dir = os.path.join(resources_dir, "Documents")

    os.makedirs(document_dir, exist_ok=True)
    os.makedirs(os.path.join(document_dir, base_url), exist_ok=True)

    shutil.copy("Info.plist", content_dir)
    shutil.copy("DASH_LICENSE", os.path.join(resources_dir, "LICENSE"))


    if not args.local:
        global_driver = webdriver.PhantomJS(executable_path="C:\\Users\\lucas\\AppData\\Roaming\\npm\\node_modules\\phantomjs-prebuilt\\lib\\phantom\\bin\phantomjs.exe")
    
        # Crawl and download powershell modules documentation
        crawl_posh_documentation(document_dir, powershell_version = args.version)
        

        # Download icon for package
        download_binary("https://github.com/PowerShell/PowerShell/raw/master/assets/Powershell_16.png", os.path.join(docset_dir, "icon.png"))
        download_binary("https://github.com/PowerShell/PowerShell/raw/master/assets/Powershell_32.png", os.path.join(docset_dir, "icon@2x.png"))

        global_driver.quit()


    # Create database and index html doc
    sqlite_filepath = os.path.join(resources_dir, "docSet.dsidx")
    if os.path.exists(sqlite_filepath):
        os.remove(sqlite_filepath)

    db = sqlite3.connect(sqlite_filepath)
    cur = db.cursor()
    cur.execute('CREATE TABLE searchIndex(id INTEGER PRIMARY KEY, name TEXT, type TEXT, path TEXT);')
    cur.execute('CREATE UNIQUE INDEX anchor ON searchIndex (name, type, path);')

    module_dir = os.path.join(document_dir, base_url)
    modules = filter(lambda x : os.path.isdir(x), map(lambda y: os.path.join(module_dir, y), os.listdir(module_dir)))
    for module in modules:

        module_name = os.path.basename(module)
        insert_into_sqlite_db(cur, module_name, "Module", "%s/%s/index.html" % (base_url, module_name))

        for f in filter(lambda x : os.path.isfile(os.path.join(module_dir, module_name, x)), os.listdir(module)):
            
            cmdlet_filename = os.path.basename(f)
            if cmdlet_filename == "index.html":
                continue

            cmdlet_name, html_ext = os.path.splitext(cmdlet_filename)
            insert_into_sqlite_db(cur, cmdlet_name, "Cmdlet", "%s/%s/%s" % (base_url, module_name, cmdlet_filename))
        

    # commit and close db
    db.commit()
    db.close()

    # output directory : $out/versions/$posh_version/Powershell.docset
    version_output_dir = os.path.join(dest_dir, "versions", "%s" % args.version)
    os.makedirs(version_output_dir, exist_ok=True)

    # tarball and gunzip the docset
    make_docset(
        docset_dir,
        version_output_dir,
        docset_name
    )

if __name__ == '__main__':

    

    parser = argparse.ArgumentParser(
        description='Dash docset creation script for Powershell modules and Cmdlets'
    )

    parser.add_argument("-vv", "--verbose", 
        help="increase output verbosity", 
        action="store_true"
    )

    parser.add_argument("-v", "--version", 
        help="select powershell API versions", 
        default = "6",
        choices = ["3.0", "4.0", "5.0", "5.1", "6"]
    )

    parser.add_argument("-t", "--temporary", 
        help="Use a temporary directory for creating docset, otherwise use current dir.", 
        default=False, 
        action="store_true"
    )

    parser.add_argument("-l", "--local", 
        help="Do not download content. Only for development use.\n" + 
             "Incompatible with --temporary option", 
        default=False, 
        action="store_true"
    )

    parser.add_argument("-o", "--output", 
        help="set output directory", 
        default = os.getcwd(),
    )

    args = parser.parse_args()
    if args.verbose:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.INFO)

    conf = Configuration( args )

    if args.temporary:

        with tempfile.TemporaryDirectory() as tmp_builddir:
            conf.build_folder = tmp_builddir
            main(conf)
    else:
        main(conf)
